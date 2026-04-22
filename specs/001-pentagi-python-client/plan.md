# Implementation Plan: PentAGI Python Client

**Feature**: 001-pentagi-python-client  
**Spec**: [spec.md](spec.md)  
**Date**: 2026-04-22

---

## Technical Context

| Decision | Resolution |
|---|---|
| HTTP client | `requests` (sync REST, supports verify/ca_cert) |
| WebSocket client | `websocket-client` (sync, `WebSocketApp` on background thread) |
| GraphQL WS protocol | Legacy Apollo `graphql-ws` subprotocol (gqlgen v0.17 + gorilla) |
| CLI framework | `click` (subcommands, auto help) |
| Config loading | `python-dotenv` |
| Packaging | `pyproject.toml` + setuptools, CLI entry point `pentagi` |
| Python minimum | 3.9 |
| TLS policy | Controlled by `PENTAGI_VERIFY_SSL` / `PENTAGI_CA_CERT` in `.env` |
| Streaming design | Sync iterator over `queue.Queue` fed by background WS thread |

---

## Output directory

All implementation artifacts go into a new top-level directory:

```
pentagi_client_pkg/
├── pentagi_client/
│   ├── __init__.py
│   ├── config.py
│   ├── models.py
│   ├── exceptions.py
│   ├── client.py
│   ├── streaming.py
│   └── cli.py
├── pyproject.toml
├── .env.example
└── tests/
    ├── __init__.py
    ├── test_config.py
    ├── test_models.py
    ├── test_client.py
    └── test_cli.py
```

---

## Phase 1: Project scaffold

### Task 1.1 — Create directory and `pyproject.toml`

Create `pentagi_client_pkg/pyproject.toml`:

```toml
[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.backends.legacy:build"

[project]
name = "pentagi-client"
version = "0.1.0"
description = "Python client for the PentAGI AI penetration testing platform"
requires-python = ">=3.9"
dependencies = [
    "requests>=2.31",
    "websocket-client>=1.7",
    "python-dotenv>=1.0",
    "click>=8.1",
]

[project.scripts]
pentagi = "pentagi_client.cli:cli"

[project.optional-dependencies]
dev = ["pytest>=8", "pytest-mock>=3", "responses>=0.25"]
```

Create `.env.example`:

```ini
PENTAGI_BASE_URL=https://localhost:8443
PENTAGI_API_TOKEN=your-api-token-here
PENTAGI_VERIFY_SSL=false
# PENTAGI_CA_CERT=/path/to/ca.pem
PENTAGI_WS_MAX_RETRIES=3
```

---

## Phase 2: Core library

### Task 2.1 — `exceptions.py`

Define the error hierarchy:

```python
class PentAGIError(Exception): ...
class ConfigError(PentAGIError): ...
class AuthError(PentAGIError): ...
class APIError(PentAGIError):
    def __init__(self, status_code: int, body: str): ...
class StreamError(PentAGIError): ...
class ConnectionError(PentAGIError): ...
```

### Task 2.2 — `config.py`

```python
@dataclass
class Config:
    base_url: str          # strips trailing slash
    api_token: str
    verify_ssl: bool = False
    ca_cert: str | None = None
    ws_max_retries: int = 3

    @classmethod
    def from_env(cls, dotenv_path: str = ".env") -> "Config":
        load_dotenv(dotenv_path)
        # validate required fields; raise ConfigError if missing
        # validate ca_cert file exists if set
        # derive ws_url from base_url (https→wss, http→ws) + /api/v1/graphql
        ...

    @property
    def rest_base(self) -> str:
        return f"{self.base_url}/api/v1"

    @property
    def ws_url(self) -> str:
        # replace scheme + append path
        ...

    @property
    def requests_verify(self) -> bool | str:
        if not self.verify_ssl:
            return False
        return self.ca_cert or True

    @property
    def ws_sslopt(self) -> dict:
        import ssl
        if not self.verify_ssl:
            return {"cert_reqs": ssl.CERT_NONE}
        if self.ca_cert:
            return {"ca_certs": self.ca_cert}
        return {}
```

### Task 2.3 — `models.py`

Use `dataclasses.dataclass` with `datetime` fields. Provide `from_dict(d: dict)` class methods that parse ISO8601 timestamps.

```python
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

class FlowStatus(str, Enum):
    created = "created"
    running = "running"
    waiting = "waiting"
    finished = "finished"
    failed = "failed"

class MessageType(str, Enum):
    answer = "answer"
    report = "report"
    thoughts = "thoughts"
    browser = "browser"
    terminal = "terminal"
    file = "file"
    search = "search"
    advice = "advice"
    ask = "ask"
    input = "input"
    done = "done"
    reconnect = "reconnect"   # synthetic, client-generated

class ResultFormat(str, Enum):
    plain = "plain"
    markdown = "markdown"
    terminal = "terminal"

@dataclass
class Flow:
    id: int
    title: str
    status: FlowStatus
    provider: str
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_dict(cls, d: dict) -> "Flow": ...

@dataclass
class Subtask:
    id: int
    task_id: int
    title: str
    description: str
    status: FlowStatus
    result: str | None
    context: str | None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_dict(cls, d: dict) -> "Subtask": ...

@dataclass
class Task:
    id: int
    flow_id: int
    title: str
    status: FlowStatus
    input: str
    result: str | None
    subtasks: list[Subtask] = field(default_factory=list)
    created_at: datetime = ...
    updated_at: datetime = ...

    @classmethod
    def from_dict(cls, d: dict) -> "Task": ...

@dataclass
class MessageLog:
    id: int | None
    flow_id: int | None
    task_id: int | None
    subtask_id: int | None
    type: MessageType
    message: str
    result: str | None
    thinking: str | None
    result_format: ResultFormat
    created_at: datetime | None
```

### Task 2.4 — `streaming.py`

Implements the sync iterator backed by a background WebSocket thread.

**Key design**:

```
StreamingManager
  ├── _queue: queue.Queue[MessageLog | _Sentinel]
  ├── _ws_thread: Thread (daemon=True)
  ├── _retry_count: int
  └── _stop_event: threading.Event

_connect_and_run():
  1. websocket.WebSocketApp(config.ws_url, ...)
  2. on_open: send {"type": "connection_init", "payload": {"Authorization": "Bearer <token>"}}
  3. on_message:
     - type == "connection_ack": send subscribe message ({"type":"start","id":"1","payload":{"query":SUBSCRIPTION}})
     - type == "ka": ignore
     - type == "data": parse payload.data.messageLogAdded → MessageLog → _queue.put()
     - type == "error": put StreamError sentinel
  4. on_close / on_error: increment retry, back-off, put reconnect message, re-run
  5. on close with TERMINAL status: put _Sentinel (stop iteration)

__iter__ / __next__:
  - get from _queue (block)
  - if sentinel → raise StopIteration
  - if StreamError sentinel → raise StreamError
  - return MessageLog
```

GraphQL subscription query used:
```graphql
subscription MessageLogAdded($flowId: ID!) {
  messageLogAdded(flowId: $flowId) {
    id type message result thinking resultFormat flowId taskId subtaskId createdAt
  }
}
```

**Reconnect logic**:
- On `on_error` or unexpected `on_close`: put synthetic `reconnect` message, sleep `min(2**attempt, 30)` seconds, re-create `WebSocketApp`
- After `ws_max_retries` consecutive failures: put `StreamError` sentinel and exit thread

**Clean close** (caller breaks loop):
- `_stop_event.set()` → `WebSocketApp.close()` → thread exits

### Task 2.5 — `client.py`

`PentAGIClient` class with:

```python
class PentAGIClient:
    def __init__(self, config: Config | None = None):
        self._cfg = config or Config.from_env()
        self._session = requests.Session()
        self._session.headers["Authorization"] = f"Bearer {self._cfg.api_token}"
        self._session.verify = self._cfg.requests_verify

    def _get(self, path: str, **params) -> dict: ...
    def _post(self, path: str, json: dict) -> dict: ...
    def _put(self, path: str, json: dict) -> dict: ...

    # Flow CRUD
    def start_flow(self, input, provider, prompt_overrides=None, restore_prompts=True) -> Flow
    def get_flow(self, flow_id: int) -> Flow
    def list_flows(self) -> list[Flow]
    def reply_to_flow(self, flow_id: int, input: str) -> None
    def stop_flow(self, flow_id: int) -> None

    # Tasks
    def get_tasks(self, flow_id: int) -> list[Task]
    def get_subtasks(self, flow_id: int, task_id: int) -> list[Subtask]
    def get_subtask(self, flow_id: int, task_id: int, subtask_id: int) -> Subtask

    # Streaming
    def messages(self, flow_id: int, types: list[str] | None = None) -> Iterator[MessageLog]
```

**Prompt restore implementation** (inside `start_flow`):
1. For each key in `prompt_overrides`, call `GET /prompts/{type}` to save original
2. Call `PUT /prompts/{type}` for each override
3. Create flow via `POST /flows/`
4. If `restore_prompts=True`, register `_restore` to run via `threading.Thread` after stream ends (or call it synchronously from `stop_flow`)

**HTTP error handling** (`_get`, `_post`, `_put`):
- `401` → raise `AuthError`
- `403` → raise `AuthError`  
- `4xx` → raise `APIError(status_code, body)`
- `5xx` → raise `APIError(status_code, body)`
- `requests.ConnectionError` → raise `ConnectionError`
- `requests.Timeout` → raise `ConnectionError`

---

## Phase 3: CLI

### Task 3.1 — `cli.py`

```python
import click
from pentagi_client import PentAGIClient
from pentagi_client.config import Config
from pentagi_client.models import MessageType

DEFAULT_VISIBLE = {MessageType.answer, MessageType.report, MessageType.ask,
                   MessageType.done, MessageType.advice}
VERBOSE_EXTRA = {MessageType.thoughts, MessageType.browser, MessageType.terminal,
                 MessageType.search, MessageType.file, MessageType.input}

@click.group()
@click.option("--env", default=".env", help="Path to .env file")
@click.pass_context
def cli(ctx, env):
    ctx.ensure_object(dict)
    ctx.obj["client"] = PentAGIClient(Config.from_env(env))

@cli.command()
@click.argument("input")
@click.option("--provider", required=True)
@click.option("--prompt-type", multiple=True)
@click.option("--prompt-text", multiple=True)
@click.option("--no-restore-prompts", is_flag=True, default=False)
@click.pass_context
def start(ctx, input, provider, prompt_type, prompt_text, no_restore_prompts): ...

@cli.command()
@click.argument("flow_id", type=int)
@click.option("--verbose", is_flag=True)
@click.option("--types", default=None)
@click.pass_context
def messages(ctx, flow_id, verbose, types): ...

@cli.command()
@click.argument("flow_id", type=int)
@click.pass_context
def tasks(ctx, flow_id): ...

@cli.command()
@click.argument("flow_id", type=int)
@click.argument("task_id", type=int)
@click.pass_context
def subtasks(ctx, flow_id, task_id): ...

@cli.command()
@click.argument("flow_id", type=int)
@click.argument("task_id", type=int)
@click.argument("subtask_id", type=int)
@click.pass_context
def subtask(ctx, flow_id, task_id, subtask_id): ...

@cli.command()
@click.argument("flow_id", type=int)
@click.argument("input")
@click.pass_context
def reply(ctx, flow_id, input): ...

@cli.command()
@click.argument("flow_id", type=int)
@click.pass_context
def stop(ctx, flow_id): ...
```

All CLI commands catch `PentAGIError`, write to stderr, and `sys.exit(1)`.

---

## Phase 4: Tests

### Task 4.1 — `test_config.py`
- Load from valid `.env` → correct fields
- Missing `PENTAGI_BASE_URL` → `ConfigError`
- Missing `PENTAGI_API_TOKEN` → `ConfigError`
- `PENTAGI_VERIFY_SSL=true` + `PENTAGI_CA_CERT` missing file → `ConfigError`
- `ws_url` derivation: `https://` → `wss://`, `http://` → `ws://`
- `requests_verify` and `ws_sslopt` values for each combination

### Task 4.2 — `test_models.py`
- `Flow.from_dict` parses ISO8601 timestamps
- `Task.from_dict` includes subtasks list
- Unknown `status` / `type` values degrade gracefully (use `.value` fallback)

### Task 4.3 — `test_client.py`
- `start_flow` calls `POST /flows/` with correct body
- `start_flow` with `prompt_overrides` calls `PUT /prompts/{type}` first
- `start_flow` with `restore_prompts=True` restores originals after stop
- `reply_to_flow` sends `action: input`
- `stop_flow` sends `action: stop`
- `get_tasks` parses task list
- 401 response → `AuthError`
- 500 response → `APIError`
- Use `responses` library to mock HTTP

### Task 4.4 — `test_cli.py`
- `pentagi start` with required args succeeds
- `pentagi start` without `--provider` exits code 2
- `pentagi messages --verbose` passes all types
- `pentagi stop FLOW_ID` calls `stop_flow`
- Use `click.testing.CliRunner`

---

## Dependency install order

```
1. exceptions.py       (no internal deps)
2. config.py           (uses exceptions)
3. models.py           (uses exceptions)
4. streaming.py        (uses config, models, exceptions)
5. client.py           (uses all above)
6. cli.py              (uses client, models)
7. tests               (uses all)
```

---

## Key integration points with PentAGI API

| Operation | Method | Path |
|---|---|---|
| Create flow | `POST` | `/api/v1/flows/` |
| Get flow | `GET` | `/api/v1/flows/{id}` |
| List flows | `GET` | `/api/v1/flows/?page=1&type=init&pageSize=-1` |
| Stop flow | `PUT` | `/api/v1/flows/{id}` body `{"action":"stop"}` |
| Reply to flow | `PUT` | `/api/v1/flows/{id}` body `{"action":"input","input":"..."}` |
| Get tasks | `GET` | `/api/v1/flows/{id}/tasks/?page=1&type=init&pageSize=-1` |
| Get subtasks | `GET` | `/api/v1/flows/{id}/tasks/{tid}/subtasks/?page=1&type=init&pageSize=-1` |
| Get subtask | `GET` | `/api/v1/flows/{id}/tasks/{tid}/subtasks/{sid}` |
| Get prompt | `GET` | `/api/v1/prompts/{type}` |
| Set prompt | `PUT` | `/api/v1/prompts/{type}` body `{"prompt":"..."}` |
| Reset prompt | `POST` | `/api/v1/prompts/{type}/default` |
| GraphQL WS | `WSS` | `/api/v1/graphql` (subprotocol: `graphql-ws`) |
