# Feature Specification: PentAGI Python Client

**Feature ID**: 001  
**Short Name**: pentagi-python-client  
**Status**: Draft  
**Created**: 2026-04-22  

---

## Overview

A self-contained Python package that allows a user or automation script to command a running PentAGI instance from the terminal or from other Python code. The package connects to an existing PentAGI deployment whose base URL is stored in a `.env` file, and exposes a simple interface covering the full lifecycle of an AI-driven penetration test: start, observe, interact, and stop.

---

## Problem Statement

PentAGI exposes a REST and GraphQL API, but there is no ready-made Python client. Users who want to automate or script penetration tests must hand-craft HTTP calls, manage authentication headers, poll for updates, and handle WebSocket subscriptions manually. This creates friction and error-prone boilerplate for every new integration.

---

## Goals

- Provide a Python package that wraps the PentAGI REST and GraphQL APIs.
- Allow a user to start, observe, interact with, and stop a penetration test using straightforward function or CLI calls.
- Keep configuration minimal: only the PentAGI base URL and an API token are required, both sourced from a `.env` file.
- Support both scripted (library) and interactive (CLI) usage patterns.

---

## Non-Goals

- This package does not host or deploy a PentAGI instance.
- It does not manage LLM provider credentials or PentAGI server configuration.
- It does not implement a GUI or web interface.
- Pause/resume of an actively running flow (mid-execution forced halt) is out of scope — the natural waiting-for-input pause point is covered.

---

## User Scenarios & Testing

### Scenario 1: Start a pentest with a custom prompt

**Actor**: Security engineer or automation script  
**Precondition**: `.env` contains `PENTAGI_BASE_URL` and `PENTAGI_API_TOKEN`; a PentAGI instance is reachable at that URL.

1. User (or script) calls the "start flow" function, providing a natural-language task description and the name of the LLM provider to use.
2. The system creates a new flow on the PentAGI instance and returns a flow ID.
3. The user can optionally supply custom agent prompt overrides before starting.

**Acceptance**: A flow is created; the returned flow ID is valid and can be used in subsequent calls.

---

### Scenario 2: Stream messages from PentAGI in real time

**Actor**: User running a monitoring script or interactive session  
**Precondition**: A flow is running.

1. User subscribes to messages for a given flow ID.
2. As PentAGI agents produce output (answers, reports, internal thoughts, tool results, questions to the user), each message is delivered to the caller as it arrives.
3. Messages include their type (`answer`, `report`, `thoughts`, `ask`, `done`, etc.), content, and timestamp.
4. When the flow ends, the stream closes cleanly.

**Acceptance**: All message types surface in real time with no loss; stream terminates when the flow finishes or is stopped.

---

### Scenario 3: Query tasks and subtasks

**Actor**: User or monitoring script  
**Precondition**: A flow exists (running or finished).

1. User requests the list of tasks for a given flow ID.
2. Each task is returned with its title, status, input description, and result (if complete).
3. For each task, the user can request its subtasks, each with title, description, status, context, and result.
4. The user can also request a single subtask by ID for detailed inspection.

**Acceptance**: All tasks and subtasks for the flow are retrievable; status reflects the current state without requiring a page reload.

---

### Scenario 4: Respond when PentAGI asks a question (natural pause/resume)

**Actor**: User or automation script  
**Precondition**: A flow has entered `waiting` status and emitted a message of type `ask`.

1. The message stream notifies the caller that the flow is waiting for input.
2. User provides a reply string.
3. The system forwards the reply to PentAGI and the flow resumes.

**Acceptance**: After sending the reply, flow status changes from `waiting` to `running`; execution continues.

---

### Scenario 5: Abort all actions immediately

**Actor**: User or automation script  
**Precondition**: A flow is running or waiting.

1. User calls the "stop flow" function with the flow ID.
2. PentAGI halts all agent activity for that flow.
3. The flow status changes to a terminal state.

**Acceptance**: After the stop call returns, the flow no longer produces new messages or spawns new tasks.

---

## Functional Requirements

### FR-01: Configuration via `.env`
The package reads the following variables from a `.env` file in the working directory (with environment variable fallback). No credentials are hard-coded.

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `PENTAGI_BASE_URL` | Yes | — | Base URL of the PentAGI instance (e.g. `https://localhost:8443`) |
| `PENTAGI_API_TOKEN` | Yes | — | Bearer token for API authentication |
| `PENTAGI_VERIFY_SSL` | No | `false` | Set to `true` to enforce TLS certificate verification |
| `PENTAGI_CA_CERT` | No | — | Path to a custom CA certificate bundle (PEM) for private/enterprise deployments |
| `PENTAGI_WS_MAX_RETRIES` | No | `3` | Max WebSocket reconnect attempts before raising an error |

### FR-02: Start a flow
The package exposes a function to create a new penetration-test flow. Inputs: task description (string, required), LLM provider name (string, required), optional custom prompt overrides (map of prompt-type → prompt-text).

### FR-03: Custom prompt override before flow start
Before starting a flow, the user may supply one or more agent prompt overrides (e.g., system prompt for the `pentester` agent). The package applies each override via the prompts API before creating the flow, then **restores the original prompts by default** once the flow completes or is stopped (`restore_prompts=True` by default). Pass `restore_prompts=False` to explicitly retain the overrides on the server after the flow ends.

### FR-04: Real-time message streaming
The package provides a **synchronous iterator** interface for live messages from a running flow. The caller writes a plain `for msg in client.messages(flow_id)` loop with no knowledge of async/await or event loops required. The underlying WebSocket connection is managed transparently on a background thread.

Each delivered message exposes: type, content, result, thinking (if present), result format, and timestamp. The iterator terminates automatically when the flow reaches a terminal state (`finished` or `failed`) or when the caller breaks out of the loop.

If the WebSocket connection drops mid-stream, the client **auto-reconnects** with exponential back-off (default: up to 3 attempts). On each reconnect attempt, a special message of type `reconnect` is emitted into the iterator so the caller can log or react. If all retry attempts are exhausted, an exception is raised and the iterator stops. The retry limit is configurable via `PENTAGI_WS_MAX_RETRIES` in `.env` (default `3`).

### FR-05: Fetch tasks and subtasks
- `get_tasks(flow_id)` — returns all tasks for a flow.
- `get_subtasks(flow_id, task_id)` — returns all subtasks for a task.
- `get_subtask(flow_id, task_id, subtask_id)` — returns a single subtask with full detail.
- Each object includes: id, title, status, description/input, result, timestamps.

### FR-06: Send user input to a waiting flow
When a flow is in `waiting` status, the package exposes a function to send a reply string that resumes the flow.

### FR-07: Stop a flow
The package exposes a function to immediately stop a flow. After the call returns, no further agent activity occurs for that flow.

### FR-08: CLI entry point
A command-line interface wraps the library functions so a user can invoke all the above operations from a terminal without writing Python code. Minimum supported commands:

The `messages` command filters output by message type. **Default visible types**: `answer`, `report`, `ask`, `done`, `advice`. The `--verbose` flag additionally shows: `thoughts`, `browser`, `terminal`, `search`, `file`, `input`. The library's streaming iterator always delivers all types; filtering is a CLI-layer concern only.

| Command | Description |
|---------|-------------|
| `start` | Start a new pentest flow |
| `messages` | Stream messages from a flow (default: `answer`, `report`, `ask`, `done`, `advice`; add `--verbose` for all types) |
| `tasks` | List tasks for a flow |
| `subtasks` | List subtasks for a task |
| `reply` | Send input to a waiting flow |
| `stop` | Stop a running flow |

### FR-09: Authenticated requests
All API calls include the bearer token from the `.env` file. If the token is missing or rejected, a clear error is surfaced to the caller.

### FR-10: Error reporting
Network errors, API errors (4xx/5xx), and authentication failures produce descriptive error messages. The caller is not exposed to raw HTTP responses.

---

## Success Criteria

| # | Criterion | Measure |
|---|-----------|---------|
| SC-01 | A new flow is created successfully | Flow ID returned within 5 seconds of calling `start` |
| SC-02 | Messages arrive in real time | First message visible within 3 seconds of the agent producing it |
| SC-03 | All tasks and subtasks are retrievable | `get_tasks` and `get_subtasks` return complete data for any valid flow |
| SC-04 | Natural pause/resume works | Flow resumes within 3 seconds of user reply being sent |
| SC-05 | Stop is immediate | Flow status reaches a terminal state within 5 seconds of `stop` call |
| SC-06 | CLI usable without code | All operations completable via terminal commands with no Python knowledge |
| SC-07 | Configuration requires no code changes | Changing base URL or token only requires updating `.env` |

---

## Key Entities

| Entity | Fields |
|--------|--------|
| Flow | id, title, status, provider, created_at, updated_at |
| Task | id, flow_id, title, status, input, result, created_at, updated_at |
| Subtask | id, task_id, title, description, status, result, context, created_at, updated_at |
| MessageLog | id, flow_id, task_id, subtask_id, type, message, result, thinking, result_format, created_at |
| Config | base_url, api_token (from .env) |

---

## Dependencies & Assumptions

### Assumptions
- The PentAGI instance is already running and reachable at the URL in `.env`.
- The API token has sufficient permissions to create and manage flows.
- Real-time message delivery uses GraphQL subscriptions over WebSocket (as confirmed by the PentAGI GraphQL schema).
- The REST API base path is `/api/v1` (confirmed from swagger spec).
- For prompt overrides, the package calls `PUT /prompts/{promptType}` before flow creation and restores originals after the flow ends by default (`restore_prompts=True`). Pass `restore_prompts=False` to retain overrides on the server.
- Python 3.9+ is assumed.
- The default PentAGI Docker deployment uses a self-signed TLS certificate (`https://localhost:8443`). TLS verification is therefore **disabled by default** (`PENTAGI_VERIFY_SSL=false`). For production deployments behind a trusted CA, users set `PENTAGI_VERIFY_SSL=true` and optionally `PENTAGI_CA_CERT` to point at a custom CA bundle.

### Dependencies (runtime)
- HTTP client library capable of WebSocket connections
- `.env` file parsing library
- No dependency on any specific PentAGI SDK (there is none)

### External Dependencies
- A live PentAGI instance (not mocked)
- Network access from the machine running the client to the PentAGI host

---

## Clarifications

### Session 2026-04-22

- Q: How should the client handle TLS/SSL certificates (PentAGI default install uses self-signed certs)? → A: `PENTAGI_VERIFY_SSL=true/false` in `.env`, default `false`; optional `PENTAGI_CA_CERT` path for custom CA bundle.
- Q: Should the streaming API be async (asyncio) or synchronous? → A: Synchronous iterator (`for msg in client.messages(flow_id)`), WebSocket managed on a background thread transparently.
- Q: What should happen when the WebSocket connection drops mid-stream? → A: Auto-reconnect up to N attempts (default 3, configurable via `PENTAGI_WS_MAX_RETRIES`) with exponential back-off; emit a `reconnect` event to the iterator on each attempt; raise after all retries exhausted.
- Q: Which message types should the CLI show by default when streaming? → A: Default shows `answer`, `report`, `ask`, `done`, `advice`; `--verbose` flag adds `thoughts`, `browser`, `terminal`, `search`, `file`, `input`. Library iterator always delivers all types; filtering is CLI-only.
- Q: What is the default behaviour for prompt restore after a flow ends? → A: Restore originals by default (`restore_prompts=True`); pass `restore_prompts=False` to retain overrides on the server.

---

## Out of Scope

- Force-pausing an actively running flow mid-execution (no API support exists)
- Managing PentAGI server configuration, providers, or users
- Persistent local storage of flow results
- Multi-user or concurrent-flow management UI
- Any GUI, web interface, or dashboard
