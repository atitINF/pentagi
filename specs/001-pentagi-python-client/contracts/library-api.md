# Library API Contract: PentAGI Python Client

**Module**: `pentagi_client`  
**Date**: 2026-04-22

---

## Public surface

Only the symbols below are considered stable public API. Internal modules (`streaming.py`, etc.) are not part of this contract.

```python
from pentagi_client import PentAGIClient
from pentagi_client.models import Flow, Task, Subtask, MessageLog
from pentagi_client.exceptions import PentAGIError, AuthError, APIError, StreamError
```

---

## PentAGIClient

```python
class PentAGIClient:
    def __init__(self, config: Config | None = None) -> None
```

If `config` is `None`, loads `Config` from `.env` / environment variables automatically.

---

### Flow operations

```python
def start_flow(
    self,
    input: str,
    provider: str,
    prompt_overrides: dict[str, str] | None = None,
    restore_prompts: bool = True,
) -> Flow
```
Creates a new flow. If `prompt_overrides` is provided, applies each `{prompt_type: text}` pair via the prompts API before creating the flow. If `restore_prompts=True` (default), restores original prompts after the flow reaches a terminal state or is stopped.

Raises: `AuthError`, `APIError`, `ConfigError`

---

```python
def get_flow(self, flow_id: int) -> Flow
```
Returns current state of a flow.

---

```python
def list_flows(self) -> list[Flow]
```
Returns all flows visible to the authenticated user.

---

```python
def reply_to_flow(self, flow_id: int, input: str) -> None
```
Sends a reply when a flow is in `waiting` status. No-op if flow is not waiting (does not raise).

Raises: `AuthError`, `APIError`

---

```python
def stop_flow(self, flow_id: int) -> None
```
Immediately stops a running or waiting flow. Idempotent — safe to call on an already-stopped flow.

Raises: `AuthError`, `APIError`

---

### Task / Subtask operations

```python
def get_tasks(self, flow_id: int) -> list[Task]
```
Returns all tasks for the given flow (each task includes its subtasks list, which may be empty).

---

```python
def get_subtasks(self, flow_id: int, task_id: int) -> list[Subtask]
```
Returns all subtasks for a specific task.

---

```python
def get_subtask(self, flow_id: int, task_id: int, subtask_id: int) -> Subtask
```
Returns a single subtask with full detail including `context` and `result`.

---

### Streaming

```python
def messages(
    self,
    flow_id: int,
    types: list[str] | None = None,
) -> Iterator[MessageLog]
```
Returns a synchronous iterator of live messages from a running flow. The underlying GraphQL subscription runs on a background thread.

- If `types` is `None`, all message types are delivered.
- If `types` is a list, only messages with a matching `type` are yielded (filtering happens client-side).
- Yields a synthetic `MessageLog(type="reconnect")` each time the WebSocket reconnects.
- Raises `StreamError` after `PENTAGI_WS_MAX_RETRIES` consecutive reconnect failures.
- The iterator terminates cleanly when the flow reaches `finished` or `failed` status (server sends a `done` message then closes the subscription).
- Breaking out of the loop sends a `stop` message to the server and closes the WebSocket.

Usage:
```python
client = PentAGIClient()
flow = client.start_flow("Scan 10.0.0.1 for vulnerabilities", provider="openai")

for msg in client.messages(flow.id):
    if msg.type == "ask":
        client.reply_to_flow(flow.id, "Yes, proceed")
    elif msg.type == "done":
        break
    print(f"[{msg.type}] {msg.message}")
```

---

## Config

```python
@dataclass
class Config:
    base_url: str
    api_token: str
    verify_ssl: bool = False
    ca_cert: str | None = None
    ws_max_retries: int = 3

    @classmethod
    def from_env(cls, dotenv_path: str = ".env") -> "Config": ...
```

`Config.from_env()` is called automatically by `PentAGIClient()`. Pass an explicit `Config` instance to override.

---

## Thread safety

`PentAGIClient` is **not** thread-safe. Use one instance per thread or protect with a lock if sharing across threads. The `messages()` iterator internally spawns a daemon background thread that is cleaned up when the iterator is exhausted or the caller breaks out.
