# Data Model: PentAGI Python Client

**Feature**: 001-pentagi-python-client  
**Date**: 2026-04-22

---

## Entities

All entities are **read-only dataclasses** representing data returned from the PentAGI API. They are never persisted locally.

---

### Config

Loaded once at startup from `.env` / environment variables.

| Field | Type | Required | Default | Source variable |
|-------|------|----------|---------|-----------------|
| `base_url` | `str` | Yes | — | `PENTAGI_BASE_URL` |
| `api_token` | `str` | Yes | — | `PENTAGI_API_TOKEN` |
| `verify_ssl` | `bool` | No | `False` | `PENTAGI_VERIFY_SSL` |
| `ca_cert` | `str \| None` | No | `None` | `PENTAGI_CA_CERT` |
| `ws_max_retries` | `int` | No | `3` | `PENTAGI_WS_MAX_RETRIES` |

**Validation rules**:
- `base_url` must be non-empty and start with `http://` or `https://`
- `api_token` must be non-empty
- `ws_max_retries` must be ≥ 0
- If `ca_cert` is set, the file must exist at startup

---

### Flow

Represents a penetration-test session.

| Field | Type | Nullable | Description |
|-------|------|----------|-------------|
| `id` | `int` | No | Unique flow identifier |
| `title` | `str` | No | Auto-generated or user-provided name |
| `status` | `FlowStatus` | No | `created \| running \| waiting \| finished \| failed` |
| `provider` | `str` | No | LLM provider name (e.g. `openai`) |
| `created_at` | `datetime` | No | Creation timestamp |
| `updated_at` | `datetime` | No | Last update timestamp |

**State transitions**:
```
created → running → waiting ⟷ running → finished
                            → failed
```

---

### Task

A high-level goal within a flow, created by the primary agent.

| Field | Type | Nullable | Description |
|-------|------|----------|-------------|
| `id` | `int` | No | Unique task identifier |
| `flow_id` | `int` | No | Parent flow |
| `title` | `str` | No | Short task name |
| `status` | `FlowStatus` | No | Mirrors flow status enum |
| `input` | `str` | No | Task description as given to the agent |
| `result` | `str` | Yes | Outcome when task is finished |
| `subtasks` | `list[Subtask]` | No | May be empty while running |
| `created_at` | `datetime` | No | |
| `updated_at` | `datetime` | No | |

---

### Subtask

A concrete action executed by a specialist agent (pentester, coder, searcher, etc.).

| Field | Type | Nullable | Description |
|-------|------|----------|-------------|
| `id` | `int` | No | Unique subtask identifier |
| `task_id` | `int` | No | Parent task |
| `title` | `str` | No | Short name |
| `description` | `str` | No | Full instructions for the agent |
| `status` | `FlowStatus` | No | |
| `result` | `str` | Yes | Output when finished |
| `context` | `str` | Yes | Additional execution context |
| `created_at` | `datetime` | No | |
| `updated_at` | `datetime` | No | |

---

### MessageLog

A single message emitted by any PentAGI agent during flow execution. The primary unit of real-time output.

| Field | Type | Nullable | Description |
|-------|------|----------|-------------|
| `id` | `int` | No | Unique message identifier |
| `flow_id` | `int` | No | Parent flow |
| `task_id` | `int` | Yes | Linked task (if scoped) |
| `subtask_id` | `int` | Yes | Linked subtask (if scoped) |
| `type` | `MessageType` | No | See enum below |
| `message` | `str` | No | Main content |
| `result` | `str` | Yes | Output/result content |
| `thinking` | `str` | Yes | Agent internal reasoning |
| `result_format` | `ResultFormat` | No | `plain \| markdown \| terminal` |
| `created_at` | `datetime` | No | |

**Special synthetic types** (client-generated, not from server):
- `reconnect` — emitted when WebSocket reconnects
- (no `id`, `flow_id` etc. — `message` contains status text)

---

## Enumerations

### FlowStatus
```
created | running | waiting | finished | failed
```

### MessageType
Server-provided values:
```
answer | report | thoughts | browser | terminal | file | search | advice | ask | input | done
```
Client-generated values:
```
reconnect
```

### ResultFormat
```
plain | markdown | terminal
```

---

## Relationships

```
Config (singleton)
  └─ used by PentAGIClient

PentAGIClient
  ├─ creates/reads → Flow (1..*)
  │     └─ has → Task (0..*)
  │               └─ has → Subtask (0..*)
  └─ streams → MessageLog (0..* per Flow)
```

---

## Error hierarchy

```
PentAGIError (base)
├── ConfigError        — missing/invalid .env values
├── AuthError          — 401/403 from API; missing token
├── APIError           — 4xx/5xx HTTP responses (carries status_code, body)
├── StreamError        — WebSocket failures after all retries exhausted
└── ConnectionError    — network-level failures (DNS, TCP timeout)
```
