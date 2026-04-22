# Research: PentAGI Python Client

**Feature**: 001-pentagi-python-client  
**Date**: 2026-04-22

---

## Decision 1: HTTP client library

**Decision**: `requests`  
**Rationale**: Synchronous, battle-tested, zero-surprise API for REST calls. All PentAGI REST endpoints (`/api/v1/*`) are standard JSON over HTTPS. `requests` supports `verify=False` and `verify='/path/to/ca.pem'` out of the box, which maps directly to the `PENTAGI_VERIFY_SSL` / `PENTAGI_CA_CERT` config requirements.  
**Alternatives considered**:
- `httpx` — supports both sync and async; heavier than needed since we're sync-only
- `urllib3` — lower level, more boilerplate
- `aiohttp` — async-only, rejected (spec requires sync interface)

---

## Decision 2: WebSocket client library

**Decision**: `websocket-client`  
**Rationale**: Synchronous WebSocket client that runs on a background thread via `WebSocketApp`. Directly supports the `graphql-ws` subprotocol header, TLS options (`sslopt`), and custom headers (for Bearer token). The background-thread model matches the spec's sync iterator requirement exactly.  
**Alternatives considered**:
- `websockets` — async-native, would require asyncio wrapper thread
- `gql` — full GraphQL client with subscription support, but heavy dependency and more complexity than needed for a single subscription pattern
- Pure `asyncio` with `websockets` on a thread — more complex than `websocket-client`'s `WebSocketApp` which already handles threading

---

## Decision 3: GraphQL WebSocket subprotocol

**Decision**: Legacy Apollo `graphql-ws` subprotocol  
**Rationale**: PentAGI uses gqlgen v0.17.57 with gorilla/websocket. gqlgen's `transport.Websocket` with gorilla implements the older `graphql-ws` subprotocol (Apollo/subscriptions-transport-ws era). Message types used:

| Direction | Type | Payload |
|-----------|------|---------|
| Client → Server | `connection_init` | `{"Authorization": "Bearer <token>"}` |
| Server → Client | `connection_ack` | — |
| Server → Client | `ka` | — (keep-alive ping) |
| Client → Server | `start` | `{"query": "...", "variables": {...}}` with `id` |
| Server → Client | `data` | `{"data": {...}}` with matching `id` |
| Server → Client | `error` | error array with matching `id` |
| Client → Server | `stop` | — with matching `id` |
| Client → Server | `connection_terminate` | — |

**Alternatives considered**:
- `graphql-transport-ws` (newer) — not used by gqlgen v0.17 with gorilla/websocket

---

## Decision 4: CLI framework

**Decision**: `click`  
**Rationale**: Mature, widely used, decorator-based subcommand design. Natural fit for a multi-command CLI (`start`, `messages`, `tasks`, `subtasks`, `reply`, `stop`). Better UX than argparse (automatic help text, type conversion). Lower overhead than `typer`.  
**Alternatives considered**:
- `argparse` — stdlib but verbose for subcommands; no auto help formatting
- `typer` — modern but adds FastAPI-style dependency; click is the more established choice for pure CLI tools

---

## Decision 5: `.env` parsing

**Decision**: `python-dotenv`  
**Rationale**: De facto standard for `.env` file loading in Python. `load_dotenv()` loads values into `os.environ` with environment variable fallback built in.  
**Alternatives considered**: None — `python-dotenv` is the clear standard.

---

## Decision 6: Package structure and packaging

**Decision**: `pyproject.toml` with `setuptools`, installed as `pentagi-client`, CLI entry point `pentagi`

```
pentagi_client/
├── __init__.py        # public API surface: PentAGIClient, models
├── client.py          # PentAGIClient class (all REST operations)
├── config.py          # Config dataclass loaded from .env / env vars
├── models.py          # Dataclasses: Flow, Task, Subtask, MessageLog
├── streaming.py       # GraphQL WebSocket subscription manager
├── exceptions.py      # PentAGIError, AuthError, StreamError, ConnectionError
└── cli.py             # Click CLI entry point (all commands)
```

**Rationale**: Clean separation — config, models, HTTP client, WebSocket stream, and CLI are independent layers. The `PentAGIClient` class is the single public API entry point for library users; `cli.py` just wraps it.

---

## Decision 7: TLS handling

**Decision**: `requests.Session` with `verify` set from config; `websocket-client` `sslopt` set from same config

| `PENTAGI_VERIFY_SSL` | `PENTAGI_CA_CERT` | `requests` `verify=` | `websocket-client` `sslopt` |
|---|---|---|---|
| `false` (default) | — | `False` | `{"cert_reqs": ssl.CERT_NONE}` |
| `true` | — | `True` | `{}` (system CA) |
| `true` | `/path/to/ca.pem` | `/path/to/ca.pem` | `{"ca_certs": "/path/to/ca.pem"}` |

**Note**: `PENTAGI_CA_CERT` is only meaningful when `PENTAGI_VERIFY_SSL=true`.

---

## Decision 8: WebSocket URL derivation

PentAGI REST base URL is `https://host:port`. GraphQL WebSocket URL is derived by:
1. Replace `https://` → `wss://` (or `http://` → `ws://`)
2. Append `/api/v1/graphql`

The `Authorization` Bearer token is sent in the `connection_init` payload (not as an HTTP header), as gqlgen's `InitFunc` extracts auth from the payload for WebSocket connections.

---

## Decision 9: Reconnect implementation

The `StreamingManager` maintains a retry counter. On disconnect:
1. Emit `MessageLog(type="reconnect", message="Reconnecting (attempt N/MAX)...")` into the queue
2. Sleep with exponential back-off: `min(2^attempt, 30)` seconds
3. Re-establish WebSocket and re-subscribe with a new message ID
4. On `MAX_RETRIES` exhaustion: emit `MessageLog(type="error", ...)` then raise `StreamError`

The synchronous iterator reads from a `queue.Queue` populated by the background WebSocket thread.
