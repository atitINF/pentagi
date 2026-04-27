from __future__ import annotations

import threading
from typing import Dict, Iterator, List, Optional

import requests as _requests

from .config import Config
from .exceptions import APIError, AuthError
from .exceptions import ConnectionError as PentAGIConnectionError
from .models import AgentLog, Assistant, AssistantLog, Flow, MessageLog, Subtask, Task
from .streaming import AssistantStreamingManager, StreamingManager


class PentAGIClient:
    def __init__(self, config: Optional[Config] = None) -> None:
        self._cfg = config or Config.from_env()
        self._session = _requests.Session()
        self._session.headers.update({
            "Authorization": f"Bearer {self._cfg.api_token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        })
        self._session.verify = self._cfg.requests_verify

    # ------------------------------------------------------------------
    # HTTP helpers
    # ------------------------------------------------------------------

    def _get(self, path: str, **params) -> dict:
        url = self._cfg.rest_base + path
        try:
            resp = self._session.get(url, params=params, timeout=30)
        except _requests.ConnectionError as exc:
            raise PentAGIConnectionError(str(exc)) from exc
        except _requests.Timeout as exc:
            raise PentAGIConnectionError("Request timed out") from exc
        return self._handle(resp)

    def _post(self, path: str, json: dict) -> dict:
        url = self._cfg.rest_base + path
        try:
            resp = self._session.post(url, json=json, timeout=30)
        except _requests.ConnectionError as exc:
            raise PentAGIConnectionError(str(exc)) from exc
        except _requests.Timeout as exc:
            raise PentAGIConnectionError("Request timed out") from exc
        return self._handle(resp)

    def _put(self, path: str, json: dict) -> dict:
        url = self._cfg.rest_base + path
        try:
            resp = self._session.put(url, json=json, timeout=30)
        except _requests.ConnectionError as exc:
            raise PentAGIConnectionError(str(exc)) from exc
        except _requests.Timeout as exc:
            raise PentAGIConnectionError("Request timed out") from exc
        return self._handle(resp)

    @staticmethod
    def _handle(resp: _requests.Response) -> dict:
        if resp.status_code in (401, 403):
            raise AuthError(f"HTTP {resp.status_code}: authentication failed")
        if not resp.ok:
            raise APIError(resp.status_code, resp.text)
        if resp.status_code == 204 or not resp.content:
            return {}
        try:
            body = resp.json()
        except Exception:
            return {}
        if isinstance(body, dict) and "data" in body:
            return body["data"]
        return body

    # ------------------------------------------------------------------
    # Flow operations
    # ------------------------------------------------------------------

    def start_flow(
        self,
        input: str,
        provider: str,
        prompt_overrides: Optional[Dict[str, str]] = None,
        restore_prompts: bool = True,
    ) -> Flow:
        originals: Dict[str, str] = {}

        if prompt_overrides:
            for prompt_type, new_text in prompt_overrides.items():
                try:
                    original = self._get(f"/prompts/{prompt_type}")
                    originals[prompt_type] = original.get("prompt", "")
                except Exception:
                    originals[prompt_type] = ""
                self._put(f"/prompts/{prompt_type}", {"prompt": new_text})

        data = self._post("/flows/", {"input": input, "provider": provider})
        flow = Flow.from_dict(data)

        if prompt_overrides and restore_prompts:
            def _restore():
                for pt in originals:
                    try:
                        self._post(f"/prompts/{pt}/default", {})
                    except Exception:
                        pass
            threading.Thread(target=_restore, daemon=True).start()

        return flow

    def get_flow(self, flow_id: int) -> Flow:
        data = self._get(f"/flows/{flow_id}")
        return Flow.from_dict(data)

    def list_flows(self) -> List[Flow]:
        data = self._get("/flows/", page=1, type="init", pageSize=-1)
        items = data.get("flows") or (data if isinstance(data, list) else [])
        return [Flow.from_dict(f) for f in items]

    def reply_to_flow(self, flow_id: int, input: str) -> None:
        self._put(f"/flows/{flow_id}", {"action": "input", "input": input})

    def stop_flow(self, flow_id: int) -> None:
        try:
            self._put(f"/flows/{flow_id}", {"action": "stop"})
        except APIError as exc:
            if exc.status_code < 500:
                return
            raise

    # ------------------------------------------------------------------
    # Task / Subtask operations
    # ------------------------------------------------------------------

    def get_tasks(self, flow_id: int) -> List[Task]:
        data = self._get(f"/flows/{flow_id}/tasks/", page=1, type="init", pageSize=-1)
        items = data.get("tasks") or (data if isinstance(data, list) else [])
        return [Task.from_dict(t) for t in items]

    def get_subtasks(self, flow_id: int, task_id: int) -> List[Subtask]:
        data = self._get(
            f"/flows/{flow_id}/tasks/{task_id}/subtasks/",
            page=1, type="init", pageSize=-1,
        )
        items = data.get("subtasks") or (data if isinstance(data, list) else [])
        return [Subtask.from_dict(s) for s in items]

    def get_subtask(self, flow_id: int, task_id: int, subtask_id: int) -> Subtask:
        data = self._get(f"/flows/{flow_id}/tasks/{task_id}/subtasks/{subtask_id}")
        return Subtask.from_dict(data)

    def get_all_subtasks(self, flow_id: int) -> List[Subtask]:
        """Return all subtasks across every task in the flow (single API call)."""
        data = self._get(f"/flows/{flow_id}/subtasks/", page=1, type="init", pageSize=-1)
        items = data.get("subtasks") or (data if isinstance(data, list) else [])
        return [Subtask.from_dict(s) for s in items]

    # ------------------------------------------------------------------
    # Assistant (conversational chat about a flow)
    # ------------------------------------------------------------------

    def create_assistant(
        self,
        flow_id: int,
        input: str,
        provider: str,
        use_agents: bool = True,
    ) -> Assistant:
        data = self._post(f"/flows/{flow_id}/assistants/", {
            "input": input,
            "provider": provider,
            "use_agents": use_agents,
        })
        return Assistant.from_dict(data)

    def reply_to_assistant(self, flow_id: int, assistant_id: int, input: str) -> None:
        self._put(f"/flows/{flow_id}/assistants/{assistant_id}", {
            "action": "input",
            "input": input,
        })

    def stop_assistant(self, flow_id: int, assistant_id: int) -> None:
        try:
            self._put(f"/flows/{flow_id}/assistants/{assistant_id}", {"action": "stop"})
        except APIError as exc:
            if exc.status_code < 500:
                return
            raise

    def wait_for_assistant_response(
        self,
        flow_id: int,
        assistant_id: int,
        seen_ids: set,
        timeout: int = 120,
        poll_interval: float = 2.0,
    ) -> List[AssistantLog]:
        """Poll assistant logs until new messages appear or timeout is reached.

        Returns only messages not already in seen_ids.
        """
        import time as _time
        deadline = _time.monotonic() + timeout
        while _time.monotonic() < deadline:
            logs = self.get_assistant_logs(flow_id, assistant_id)
            new = [m for m in logs if m.id not in seen_ids]
            if new:
                return new
            _time.sleep(poll_interval)
        return []

    def get_assistant_logs(self, flow_id: int, assistant_id: int) -> List[AssistantLog]:
        """Fetch historical assistant log entries for a specific assistant."""
        data = self._get(f"/flows/{flow_id}/assistantlogs/", page=1, type="init", pageSize=-1)
        items = data.get("assistantlogs") or (data if isinstance(data, list) else [])
        logs = [AssistantLog.from_dict(m) for m in items]
        return [log for log in logs if log.assistant_id == assistant_id]

    def get_all_assistant_logs(self, flow_id: int) -> List[AssistantLog]:
        """Fetch all assistant logs for a flow, sorted by creation time."""
        data = self._get(f"/flows/{flow_id}/assistantlogs/", page=1, type="init", pageSize=-1)
        items = data.get("assistantlogs") or (data if isinstance(data, list) else [])
        return [AssistantLog.from_dict(m) for m in items]

    def open_assistant_stream(
        self,
        flow_id: int,
        assistant_id: int,
        debug: bool = False,
    ) -> "AssistantStreamingManager":
        """Return a started AssistantStreamingManager (WS connects immediately).

        Caller is responsible for calling .close() when done.
        """
        return AssistantStreamingManager(self._cfg, flow_id, assistant_id, debug=debug)

    def assistant_messages(
        self,
        flow_id: int,
        assistant_id: int,
        debug: bool = False,
    ) -> Iterator[AssistantLog]:
        manager = AssistantStreamingManager(self._cfg, flow_id, assistant_id, debug=debug)
        try:
            for msg in manager:
                yield msg
        finally:
            manager.close()

    # ------------------------------------------------------------------
    # Usage / analytics
    # ------------------------------------------------------------------

    def get_usage(self) -> dict:
        """System-wide token usage and analytics for the authenticated user."""
        return self._get("/usage/")

    def get_period_usage(self, period: str) -> dict:
        """Time-series usage analytics. period must be 'week', 'month', or 'quarter'."""
        if period not in ("week", "month", "quarter"):
            raise ValueError(f"period must be 'week', 'month', or 'quarter', got {period!r}")
        return self._get(f"/usage/{period}")

    def get_flow_usage(self, flow_id: int) -> dict:
        """Token usage and analytics scoped to a single flow."""
        return self._get(f"/flows/{flow_id}/usage/")

    # ------------------------------------------------------------------
    # Agent logs
    # ------------------------------------------------------------------

    def get_agent_logs(
        self,
        flow_id: int,
        task_id: Optional[int] = None,
        subtask_id: Optional[int] = None,
    ) -> List[AgentLog]:
        """Fetch agent interaction logs for a flow, optionally filtered by task/subtask."""
        data = self._get(f"/flows/{flow_id}/agentlogs/", page=1, type="init", pageSize=-1)
        items = data.get("agentlogs") or (data if isinstance(data, list) else [])
        logs = [AgentLog.from_dict(i) for i in items]
        if task_id is not None:
            logs = [l for l in logs if l.task_id == task_id]
        if subtask_id is not None:
            logs = [l for l in logs if l.subtask_id == subtask_id]
        return logs

    # ------------------------------------------------------------------
    # Streaming
    # ------------------------------------------------------------------

    def get_messages(self, flow_id: int) -> List[MessageLog]:
        data = self._get(f"/flows/{flow_id}/msglogs/", page=1, type="init", pageSize=-1)
        items = data.get("msglogs") or (data if isinstance(data, list) else [])
        return [MessageLog.from_dict(m) for m in items]

    def messages(
        self,
        flow_id: int,
        types: Optional[List[str]] = None,
        debug: bool = False,
    ) -> Iterator[MessageLog]:
        manager = StreamingManager(self._cfg, flow_id, debug=debug)
        type_filter = set(types) if types else None
        try:
            for msg in manager:
                if type_filter is None or msg.type.value in type_filter:
                    yield msg
        finally:
            manager.close()
