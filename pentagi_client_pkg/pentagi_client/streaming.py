from __future__ import annotations

import json
import queue
import threading
import time
from typing import Iterator, Optional

import websocket

from .config import Config
from .exceptions import StreamError
from .models import MessageLog, MessageType

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

    def __init__(self, config: Config, flow_id: int) -> None:
        self._cfg = config
        self._flow_id = flow_id
        self._queue: queue.Queue = queue.Queue()
        self._stop_event = threading.Event()
        self._retry_count = 0
        self._msg_id = "1"
        self._ws: Optional[websocket.WebSocketApp] = None
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    # ------------------------------------------------------------------
    # Iterator protocol
    # ------------------------------------------------------------------

    def __iter__(self) -> Iterator[MessageLog]:
        return self

    def __next__(self) -> MessageLog:
        while True:
            item = self._queue.get()
            if item is _SENTINEL:
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

    def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                self._connect_and_run()
            except Exception:
                pass

            if self._stop_event.is_set():
                break

            self._retry_count += 1
            if self._retry_count > self._cfg.ws_max_retries:
                err = StreamError(
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

            if msg_type == "connection_ack":
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
                    return
                data = (payload.get("data") or {}).get("messageLogAdded")
                if data:
                    log = MessageLog.from_dict(data)
                    self._queue.put(log)
                    if log.type == MessageType.done:
                        self._stop_event.set()
                        ws.close()

            elif msg_type == "error":
                ws.close()

            elif msg_type == "complete":
                self._stop_event.set()
                ws.close()

        def on_error(ws, error):
            pass  # reconnect handled in _run

        def on_close(ws, close_status_code, close_msg):
            pass

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
