from __future__ import annotations

import json
import queue
import sys
import threading
import time
from typing import Iterator, List, Optional

import websocket

from .config import Config
from .exceptions import StreamError
from .models import AssistantLog, MessageLog, MessageType

_SUBSCRIPTION_QUERY = """
subscription MessageLogAdded($flowId: ID!) {
  messageLogAdded(flowId: $flowId) {
    id
    type
    message
    result
    thinking
    resultFormat
    flowId
    taskId
    subtaskId
    createdAt
  }
}
"""

_SENTINEL = object()


class StreamingManager:
    """
    Manages a GraphQL subscription (graphql-ws protocol) over WebSocket.
    Delivers MessageLog objects through a synchronous iterator backed by
    an internal queue fed from a background daemon thread.
    """

    def __init__(self, config: Config, flow_id: int, debug: bool = False) -> None:
        self._debug = debug
        self._cfg = config
        self._flow_id = flow_id
        self._queue: queue.Queue = queue.Queue()
        self._stop_event = threading.Event()
        self._retry_count = 0
        self._msg_id = "1"
        self._ws: Optional[websocket.WebSocketApp] = None
        self._last_error: Optional[str] = None
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    # ------------------------------------------------------------------
    # Iterator protocol
    # ------------------------------------------------------------------

    def __iter__(self) -> Iterator[MessageLog]:
        return self

    def __next__(self) -> MessageLog:
        # Give the background thread up to 10 s to connect before surfacing
        # a helpful error instead of blocking forever.
        item = self._queue.get(timeout=None)
        if item is _SENTINEL:
            if self._last_error:
                raise StreamError(self._last_error)
            raise StopIteration
        if isinstance(item, StreamError):
            raise item
        return item

    def close(self) -> None:
        self._stop_event.set()
        if self._ws is not None:
            try:
                self._ws.close()
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Background thread
    # ------------------------------------------------------------------

    def _dbg(self, msg: str) -> None:
        if self._debug:
            print(f"[WS] {msg}", file=sys.stderr, flush=True)

    def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                self._connect_and_run()
            except StopIteration:
                return
            except Exception as exc:
                self._last_error = str(exc)
                self._dbg(f"exception in _connect_and_run: {exc}")

            if self._stop_event.is_set():
                break

            self._retry_count += 1
            if self._retry_count > self._cfg.ws_max_retries:
                err = StreamError(
                    self._last_error or
                    f"WebSocket stream failed after {self._cfg.ws_max_retries} retries"
                )
                self._queue.put(err)
                self._queue.put(_SENTINEL)
                return

            delay = min(2 ** self._retry_count, 30)
            self._queue.put(
                MessageLog.synthetic(
                    MessageType.reconnect,
                    f"Reconnecting (attempt {self._retry_count}/{self._cfg.ws_max_retries})…",
                )
            )
            for _ in range(int(delay * 10)):
                if self._stop_event.is_set():
                    self._queue.put(_SENTINEL)
                    return
                time.sleep(0.1)

        self._queue.put(_SENTINEL)

    def _connect_and_run(self) -> None:
        connected = threading.Event()
        subscribed = threading.Event()

        def on_open(ws):
            connected.set()
            self._dbg(f"connected to {self._cfg.ws_url}")
            ws.send(json.dumps({
                "type": "connection_init",
                "payload": {"Authorization": f"Bearer {self._cfg.api_token}"},
            }))

        def on_message(ws, raw):
            if self._stop_event.is_set():
                ws.close()
                return
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                return

            msg_type = msg.get("type", "")
            self._dbg(f"← {msg_type}")

            if msg_type == "connection_ack":
                self._dbg("subscribed to messageLogAdded")
                ws.send(json.dumps({
                    "type": "start",
                    "id": self._msg_id,
                    "payload": {
                        "query": _SUBSCRIPTION_QUERY,
                        "variables": {"flowId": str(self._flow_id)},
                    },
                }))
                subscribed.set()

            elif msg_type == "ka":
                pass  # keep-alive, ignore

            elif msg_type == "data":
                payload = msg.get("payload", {})
                errors = payload.get("errors")
                if errors:
                    self._dbg(f"server errors: {errors}")
                    return
                data = (payload.get("data") or {}).get("messageLogAdded")
                if data:
                    log = MessageLog.from_dict(data)
                    self._dbg(f"message: type={log.type.value}")
                    self._queue.put(log)
                    # Only stop on flow-level done (subtask_id is None).
                    # Subtask completions also emit done but should not end the stream.
                    if log.type == MessageType.done and log.subtask_id is None:
                        self._stop_event.set()
                        ws.close()

            elif msg_type == "error":
                self._dbg(f"server error frame: {msg}")
                ws.close()

            elif msg_type == "complete":
                self._stop_event.set()
                ws.close()

        def on_error(ws, error):
            self._last_error = str(error)
            self._dbg(f"on_error: {error}")

        def on_close(ws, close_status_code, close_msg):
            self._dbg(f"on_close: code={close_status_code} msg={close_msg}")

        self._ws = websocket.WebSocketApp(
            self._cfg.ws_url,
            subprotocols=["graphql-ws"],
            header=[f"Authorization: Bearer {self._cfg.api_token}"],
            on_open=on_open,
            on_message=on_message,
            on_error=on_error,
            on_close=on_close,
        )

        self._ws.run_forever(sslopt=self._cfg.ws_sslopt)
        self._ws = None

        if self._stop_event.is_set():
            self._queue.put(_SENTINEL)
            raise StopIteration


# ---------------------------------------------------------------------------
# Assistant streaming
# ---------------------------------------------------------------------------

_ASSISTANT_SUBSCRIPTION_QUERY = """
subscription AssistantLogAdded($flowId: ID!) {
  assistantLogAdded(flowId: $flowId) {
    id
    type
    message
    result
    thinking
    resultFormat
    appendPart
    flowId
    assistantId
    createdAt
  }
}
"""


class AssistantStreamingManager:
    """
    Subscribes to assistantLogAdded for a given flow and assistant.
    Delivers AssistantLog objects through a synchronous iterator.
    The iterator pauses (blocks) after each 'done' message until
    resume() is called, allowing the caller to send a new input first.
    """

    def __init__(self, config: Config, flow_id: int, assistant_id: int, debug: bool = False) -> None:
        self._debug = debug
        self._cfg = config
        self._flow_id = flow_id
        self._assistant_id = assistant_id
        self._queue: queue.Queue = queue.Queue()
        self._stop_event = threading.Event()
        self._retry_count = 0
        self._msg_id = "1"
        self._ws: Optional[websocket.WebSocketApp] = None
        self._last_error: Optional[str] = None
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def __iter__(self):
        return self

    def __next__(self) -> AssistantLog:
        item = self._queue.get()
        if item is _SENTINEL:
            if self._last_error:
                raise StreamError(self._last_error)
            raise StopIteration
        if isinstance(item, StreamError):
            raise item
        return item

    def close(self) -> None:
        self._stop_event.set()
        if self._ws is not None:
            try:
                self._ws.close()
            except Exception:
                pass
        self._queue.put(_SENTINEL)

    def _dbg(self, msg: str) -> None:
        if self._debug:
            print(f"[WS-assistant] {msg}", file=sys.stderr, flush=True)

    def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                self._connect_and_run()
            except StopIteration:
                return
            except Exception as exc:
                self._last_error = str(exc)
                self._dbg(f"exception in _connect_and_run: {exc}")

            if self._stop_event.is_set():
                break

            self._retry_count += 1
            if self._retry_count > self._cfg.ws_max_retries:
                err = StreamError(
                    self._last_error or
                    f"Assistant stream failed after {self._cfg.ws_max_retries} retries"
                )
                self._queue.put(err)
                self._queue.put(_SENTINEL)
                return

            delay = min(2 ** self._retry_count, 30)
            self._queue.put(AssistantLog.synthetic(
                MessageType.reconnect,
                f"Reconnecting (attempt {self._retry_count}/{self._cfg.ws_max_retries})…",
            ))
            for _ in range(int(delay * 10)):
                if self._stop_event.is_set():
                    self._queue.put(_SENTINEL)
                    return
                time.sleep(0.1)

        self._queue.put(_SENTINEL)

    def _connect_and_run(self) -> None:
        def on_open(ws):
            self._dbg(f"connected to {self._cfg.ws_url}")
            ws.send(json.dumps({
                "type": "connection_init",
                "payload": {"Authorization": f"Bearer {self._cfg.api_token}"},
            }))

        def on_message(ws, raw):
            if self._stop_event.is_set():
                ws.close()
                return
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                return

            msg_type = msg.get("type", "")
            self._dbg(f"← {msg_type}")

            if msg_type == "connection_ack":
                self._dbg("subscribed to assistantLogAdded")
                ws.send(json.dumps({
                    "type": "start",
                    "id": self._msg_id,
                    "payload": {
                        "query": _ASSISTANT_SUBSCRIPTION_QUERY,
                        "variables": {"flowId": str(self._flow_id)},
                    },
                }))

            elif msg_type == "ka":
                pass

            elif msg_type == "data":
                payload = msg.get("payload", {})
                errors = payload.get("errors")
                if errors:
                    self._dbg(f"server errors: {errors}")
                    return
                data = (payload.get("data") or {}).get("assistantLogAdded")
                if data:
                    aid = data.get("assistantId")
                    if aid is not None and int(aid) != self._assistant_id:
                        self._dbg(f"skipping msg for assistant {aid} (want {self._assistant_id})")
                        return
                    log = AssistantLog.from_dict(data)
                    self._dbg(f"message: type={log.type.value}")
                    self._queue.put(log)

            elif msg_type == "error":
                self._dbg(f"server error frame: {msg}")
                ws.close()

            elif msg_type == "complete":
                self._stop_event.set()
                ws.close()

        def on_error(ws, error):
            self._last_error = str(error)
            self._dbg(f"on_error: {error}")

        def on_close(ws, close_status_code, close_msg):
            self._dbg(f"on_close: code={close_status_code} msg={close_msg}")

        self._ws = websocket.WebSocketApp(
            self._cfg.ws_url,
            subprotocols=["graphql-ws"],
            header=[f"Authorization: Bearer {self._cfg.api_token}"],
            on_open=on_open,
            on_message=on_message,
            on_error=on_error,
            on_close=on_close,
        )
        self._ws.run_forever(sslopt=self._cfg.ws_sslopt)
        self._ws = None

        if self._stop_event.is_set():
            self._queue.put(_SENTINEL)
            raise StopIteration
