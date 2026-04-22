# Tasks: PentAGI Python Client

**Feature**: 001-pentagi-python-client  
**Plan**: [plan.md](plan.md) | **Spec**: [spec.md](spec.md)  
**Generated**: 2026-04-22  
**Total tasks**: 35

---

## User Stories

| ID | Story | Priority | Independent test criteria |
|----|-------|----------|--------------------------|
| US1 | Start a pentest with a custom prompt | P1 | `PentAGIClient().start_flow(input, provider)` returns a `Flow` with a valid integer `id` |
| US2 | Stream live messages from a running flow | P2 | `for msg in client.messages(flow_id)` yields `MessageLog` objects; iterator closes on flow end |
| US3 | Query tasks and subtasks | P3 | `get_tasks(flow_id)` returns a list of `Task`; `get_subtasks(flow_id, task_id)` returns `Subtask` list |
| US4 | Reply to a waiting flow (natural pause/resume) | P4 | After `reply_to_flow(flow_id, text)`, the REST call sends `{"action":"input","input":text}` |
| US5 | Abort all actions immediately | P5 | After `stop_flow(flow_id)`, the REST call sends `{"action":"stop"}`; no further messages emitted |

---

## Phase 1 — Project Scaffold

**Goal**: Establish installable package skeleton with all dependencies declared.

- [x] T001 Create top-level directory `pentagi_client_pkg/` with sub-directories `pentagi_client/` and `tests/`
- [x] T002 Create `pentagi_client_pkg/pyproject.toml` with dependencies: `requests>=2.31`, `websocket-client>=1.7`, `python-dotenv>=1.0`, `click>=8.1`; dev extras: `pytest>=8`, `pytest-mock>=3`, `responses>=0.25`; CLI entry point `pentagi = "pentagi_client.cli:cli"`
- [x] T003 Create `pentagi_client_pkg/.env.example` with all five variables: `PENTAGI_BASE_URL`, `PENTAGI_API_TOKEN`, `PENTAGI_VERIFY_SSL=false`, `PENTAGI_CA_CERT` (commented out), `PENTAGI_WS_MAX_RETRIES=3`
- [x] T004 Create empty `pentagi_client_pkg/tests/__init__.py` and placeholder `pentagi_client_pkg/pentagi_client/__init__.py`

---

## Phase 2 — Foundational (blocks all user stories)

**Goal**: Config loading, error hierarchy, and shared enums ready before any story begins.

- [x] T005 Create `pentagi_client_pkg/pentagi_client/exceptions.py` with hierarchy: `PentAGIError` → `ConfigError`, `AuthError`, `APIError(status_code, body)`, `StreamError`, `ConnectionError`
- [x] T006 Create `pentagi_client_pkg/pentagi_client/config.py` with `Config` dataclass: fields `base_url`, `api_token`, `verify_ssl=False`, `ca_cert=None`, `ws_max_retries=3`; classmethod `from_env(dotenv_path=".env")`; properties `rest_base`, `ws_url` (https→wss), `requests_verify` (bool or path), `ws_sslopt` (dict for websocket-client); raise `ConfigError` for missing required fields or non-existent `ca_cert` path
- [x] T007 [P] Create enums in `pentagi_client_pkg/pentagi_client/models.py`: `FlowStatus` (created/running/waiting/finished/failed), `MessageType` (answer/report/thoughts/browser/terminal/file/search/advice/ask/input/done/reconnect), `ResultFormat` (plain/markdown/terminal)
- [x] T008 [P] Write tests for `Config.from_env()` in `pentagi_client_pkg/tests/test_config.py`: valid env loads correctly; missing `PENTAGI_BASE_URL` raises `ConfigError`; missing `PENTAGI_API_TOKEN` raises `ConfigError`; `ws_url` converts `https://` → `wss://` and `http://` → `ws://`; `requests_verify` returns `False` when `verify_ssl=false`, path string when `ca_cert` set; `ws_sslopt` returns `ssl.CERT_NONE` dict when `verify_ssl=false`

---

## Phase 3 — US1: Start a pentest with a custom prompt

**Story goal**: User can create a flow by providing a task description and provider name. Optionally supply prompt overrides that are auto-restored after flow ends.  
**Independent test**: `PentAGIClient().start_flow("Scan 10.0.0.1", "openai")` returns `Flow(id=42, status=FlowStatus.created)` (mocked HTTP)

- [x] T009 Add `Flow` dataclass to `pentagi_client_pkg/pentagi_client/models.py` with fields: `id: int`, `title: str`, `status: FlowStatus`, `provider: str`, `created_at: datetime`, `updated_at: datetime`; classmethod `from_dict(d: dict) -> Flow` parsing ISO8601 timestamps
- [x] T010 Create `pentagi_client_pkg/pentagi_client/client.py` with `PentAGIClient.__init__(config=None)` that calls `Config.from_env()` if no config given; set up `requests.Session` with `Authorization: Bearer` header and `verify` from `config.requests_verify`
- [x] T011 Implement `_get(path, **params) -> dict`, `_post(path, json) -> dict`, `_put(path, json) -> dict` private helpers in `pentagi_client_pkg/pentagi_client/client.py`; map HTTP 401/403 → `AuthError`; 4xx/5xx → `APIError(status_code, body)`; `requests.ConnectionError`/`Timeout` → `ConnectionError`
- [x] T012 Implement `PentAGIClient.start_flow(input, provider, prompt_overrides=None, restore_prompts=True) -> Flow` in `pentagi_client_pkg/pentagi_client/client.py`: if `prompt_overrides` given, `GET /prompts/{type}` for each to save original, then `PUT /prompts/{type}` to apply; `POST /flows/` with `{"input": input, "provider": provider}`; if `restore_prompts=True` register restore via `threading.Thread` to call `POST /prompts/{type}/default` after flow reaches terminal state
- [x] T013 [P] [US1] Create `pentagi_client_pkg/pentagi_client/cli.py` with `@click.group()` CLI skeleton and `start` command: positional `INPUT`, `--provider` (required), `--prompt-type`/`--prompt-text` (repeatable pairs), `--no-restore-prompts` flag; calls `client.start_flow()`; prints `Flow created: id=N title="..."` on success; catches `PentAGIError`, writes to stderr, exits 1
- [x] T014 [P] [US1] Write tests for `start_flow()` in `pentagi_client_pkg/tests/test_client.py` using `responses` library: successful call posts to `/api/v1/flows/` with correct body; `prompt_overrides` triggers GET then PUT before flow creation; 401 response raises `AuthError`; 500 response raises `APIError`
- [x] T015 [P] [US1] Write CLI tests for `start` command in `pentagi_client_pkg/tests/test_cli.py` using `click.testing.CliRunner`: missing `--provider` exits code 2; successful run prints flow id; `PentAGIError` exits code 1 with message on stderr

---

## Phase 4 — US2: Stream live messages from a running flow

**Story goal**: Caller can iterate over live messages from a running flow using a plain `for` loop. WebSocket reconnects automatically up to `PENTAGI_WS_MAX_RETRIES` times.  
**Independent test**: Mock WebSocket delivers 3 `data` frames then closes → iterator yields 3 `MessageLog` objects then stops

- [x] T016 Add `MessageLog` dataclass to `pentagi_client_pkg/pentagi_client/models.py`: fields `id: int | None`, `flow_id: int | None`, `task_id: int | None`, `subtask_id: int | None`, `type: MessageType`, `message: str`, `result: str | None`, `thinking: str | None`, `result_format: ResultFormat`, `created_at: datetime | None`; classmethod `from_dict(d: dict) -> MessageLog`
- [x] T017 Create `pentagi_client_pkg/pentagi_client/streaming.py` with `StreamingManager` class: constructor accepts `config: Config`, `flow_id: int`; internal `queue.Queue`, `threading.Event` for stop signal, retry counter; implement `_build_subscribe_payload(msg_id)` returning the `graphql-ws` protocol `start` message with the `messageLogAdded` subscription query and `flowId` variable
- [x] T018 Implement `StreamingManager._connect_and_run()` in `pentagi_client_pkg/pentagi_client/streaming.py`: create `websocket.WebSocketApp` with `subprotocols=["graphql-ws"]`, `header=["Authorization: Bearer <token>"]`, `sslopt` from config; `on_open` → send `connection_init` with auth payload; `on_message` → handle `connection_ack` (send subscribe), `ka` (ignore), `data` (parse `messageLogAdded` → `MessageLog` → `queue.put`), `error` (put sentinel); `on_close`/`on_error` → trigger reconnect logic
- [x] T019 Implement reconnect loop in `pentagi_client_pkg/pentagi_client/streaming.py`: on disconnect emit synthetic `MessageLog(type=MessageType.reconnect, message="Reconnecting (N/MAX)...")` to queue; sleep `min(2**attempt, 30)` seconds; re-call `_connect_and_run()`; after `max_retries` exhausted raise `StreamError` and put stop sentinel
- [x] T020 Implement `PentAGIClient.messages(flow_id, types=None) -> Iterator[MessageLog]` in `pentagi_client_pkg/pentagi_client/client.py`: instantiate `StreamingManager`; start background daemon thread; yield from queue until sentinel; filter by `types` list if provided (client-side); on `StopIteration` send `stop` message and set stop event
- [x] T021 [P] [US2] Add `messages` CLI command to `pentagi_client_pkg/pentagi_client/cli.py`: positional `FLOW_ID`; `--verbose` flag; `--types` option (comma-separated); default visible set `{answer, report, ask, done, advice}`; print `[HH:MM:SS] [TYPE] content` per message; Ctrl-C cleanly stops iterator
- [x] T022 [P] [US2] Write streaming tests in `pentagi_client_pkg/tests/test_client.py`: mock `WebSocketApp` delivers 3 data frames → 3 `MessageLog` objects yielded; `types` filter excludes non-matching types; disconnect triggers reconnect message in iterator; retry exhaustion raises `StreamError`

---

## Phase 5 — US3: Query tasks and subtasks

**Story goal**: Caller can fetch the full task/subtask tree for any flow.  
**Independent test**: `get_tasks(42)` returns list of `Task` objects each with a `subtasks` list; `get_subtask(42, 1, 2)` returns a `Subtask` with `description` and `result` fields

- [x] T023 [P] Add `Subtask` and `Task` dataclasses to `pentagi_client_pkg/pentagi_client/models.py`: `Subtask` fields: `id`, `task_id`, `title`, `description`, `status: FlowStatus`, `result`, `context`, `created_at`, `updated_at`; `Task` fields: `id`, `flow_id`, `title`, `status`, `input`, `result`, `subtasks: list[Subtask]`, `created_at`, `updated_at`; both with `from_dict()` classmethods
- [x] T024 Implement `get_tasks(flow_id)`, `get_subtasks(flow_id, task_id)`, `get_subtask(flow_id, task_id, subtask_id)` in `pentagi_client_pkg/pentagi_client/client.py`: all use `_get()` with `page=1&type=init&pageSize=-1` pagination params; `get_tasks` parses nested subtasks array from response
- [x] T025 [P] [US3] Add `tasks`, `subtasks`, `subtask` commands to `pentagi_client_pkg/pentagi_client/cli.py`: `tasks FLOW_ID` prints two-column table (ID, STATUS, TITLE); `subtasks FLOW_ID TASK_ID` same format; `subtask FLOW_ID TASK_ID SUBTASK_ID` prints structured key-value block (ID / Title / Status / Description / Result / Context)
- [x] T026 [P] [US3] Write task/subtask fetch tests in `pentagi_client_pkg/tests/test_client.py` using `responses`: `get_tasks` returns list of `Task` with parsed `subtasks`; `get_subtask` returns single `Subtask` with all fields; 404 raises `APIError`

---

## Phase 6 — US4: Reply to a waiting flow (natural pause/resume)

**Story goal**: When a flow emits an `ask` message and enters `waiting` status, the caller can send a reply string that resumes execution.  
**Independent test**: `reply_to_flow(42, "proceed")` sends `PUT /api/v1/flows/42` with body `{"action":"input","input":"proceed"}`

- [x] T027 Implement `PentAGIClient.reply_to_flow(flow_id, input) -> None` in `pentagi_client_pkg/pentagi_client/client.py` using `_put(f"/flows/{flow_id}", {"action": "input", "input": input})`; no error if flow is not in waiting state (API is idempotent)
- [x] T028 [P] [US4] Add `reply` command to `pentagi_client_pkg/pentagi_client/cli.py`: positional `FLOW_ID` and `INPUT`; calls `reply_to_flow()`; prints `Reply sent to flow N.` on success
- [x] T029 [P] [US4] Write tests for `reply_to_flow()` in `pentagi_client_pkg/tests/test_client.py`: verifies PUT body contains `action=input` and correct `input` text; 401 raises `AuthError`

---

## Phase 7 — US5: Abort all actions immediately

**Story goal**: Caller can halt a running or waiting flow; no further messages or tasks are produced after the call returns.  
**Independent test**: `stop_flow(42)` sends `PUT /api/v1/flows/42` with body `{"action":"stop"}`; calling on an already-stopped flow does not raise

- [x] T030 Implement `PentAGIClient.stop_flow(flow_id) -> None` in `pentagi_client_pkg/pentagi_client/client.py` using `_put(f"/flows/{flow_id}", {"action": "stop"})`; idempotent (swallow `APIError` with 4xx if flow already terminal)
- [x] T031 [P] [US5] Add `stop` command to `pentagi_client_pkg/pentagi_client/cli.py`: positional `FLOW_ID`; calls `stop_flow()`; prints `Flow N stopped.` on success; exits 1 on `PentAGIError`
- [x] T032 [P] [US5] Write tests for `stop_flow()` in `pentagi_client_pkg/tests/test_client.py`: verifies PUT body `{"action":"stop"}`; call on already-finished flow does not raise

---

## Phase 8 — Polish & Cross-Cutting Concerns

**Goal**: Complete public API surface, exports, supporting helpers.

- [x] T033 [P] Implement `PentAGIClient.get_flow(flow_id) -> Flow` and `list_flows() -> list[Flow]` in `pentagi_client_pkg/pentagi_client/client.py`; `list_flows` uses `GET /flows/?page=1&type=init&pageSize=-1`
- [x] T034 Populate `pentagi_client_pkg/pentagi_client/__init__.py` with public exports: `from .client import PentAGIClient`; `from .config import Config`; `from .models import Flow, Task, Subtask, MessageLog, FlowStatus, MessageType, ResultFormat`; `from .exceptions import PentAGIError, AuthError, APIError, StreamError, ConfigError, ConnectionError`
- [x] T035 [P] Write smoke integration test outline in `pentagi_client_pkg/tests/test_client.py` (fully mocked, no live server): instantiate client → start_flow → messages (3 synthetic) → stop_flow; assert all return types correct and no exceptions raised

---

## Dependencies (story completion order)

```
Phase 1 (Scaffold)
  └─ Phase 2 (Foundational: Config + Enums + Exceptions)
       ├─ Phase 3 (US1: Start flow)          ← P1, must complete first
       │    └─ Phase 4 (US2: Stream)         ← needs Flow model from US1
       │         └─ Phase 5 (US3: Tasks)     ← independent of US2, needs T009-T011
       │              ├─ Phase 6 (US4: Reply)   ← independent, needs T010-T011
       │              └─ Phase 7 (US5: Stop)    ← independent, needs T010-T011
       └─ Phase 8 (Polish)                   ← after all stories
```

**US4 and US5** only need `client.py`'s `_put` helper (T011) and have no dependency on US2 or US3. They can run in parallel with Phase 4 and Phase 5 once T011 is complete.

---

## Parallel execution opportunities

### After T011 (HTTP helpers done):
- T013, T014, T015 (US1 CLI + tests) — parallel with each other
- T016–T022 (US2 streaming) — starts independently
- T023–T026 (US3 tasks) — starts independently
- T027–T029 (US4 reply) — starts independently
- T030–T032 (US5 stop) — starts independently

### Within US2:
- T021 (CLI messages) and T022 (streaming tests) — parallel after T020

### Within US3:
- T023 (model dataclasses) and T025 (CLI commands), T026 (tests) — parallel after T024

### Within US4:
- T028 (CLI reply) and T029 (tests) — parallel after T027

### Within US5:
- T031 (CLI stop) and T032 (tests) — parallel after T030

---

## Implementation strategy

**MVP scope (US1 only — 15 tasks)**: T001–T015  
Delivers: installable package, `.env` config, `PentAGIClient.start_flow()`, CLI `start` command, full test coverage for config and flow creation.

**Increment 2 (US2 — 7 tasks)**: T016–T022  
Adds: live message streaming, CLI `messages --verbose`, reconnect resilience.

**Increment 3 (US3–US5 — 10 tasks)**: T023–T032  
Adds: task/subtask queries, reply, stop — completes all five user stories.

**Increment 4 (Polish — 3 tasks)**: T033–T035  
Adds: `list_flows`, `get_flow`, public `__init__.py` exports, smoke test.
