# CLI Contract: PentAGI Python Client

**Entry point**: `pentagi`  
**Date**: 2026-04-22

All commands read config from `.env` in the working directory (or env vars). All commands exit with code `0` on success, `1` on error, `2` on usage error.

---

## Global options

```
pentagi [--env FILE] <command> [options]
```

| Option | Default | Description |
|--------|---------|-------------|
| `--env FILE` | `.env` | Path to the `.env` file |

---

## Commands

### `start` — Start a new pentest flow

```
pentagi start --provider PROVIDER [--prompt-type TYPE --prompt-text TEXT]... [--no-restore-prompts] INPUT
```

| Argument / Option | Required | Description |
|---|---|---|
| `INPUT` | Yes | Natural-language task description |
| `--provider` | Yes | LLM provider name (e.g. `openai`, `anthropic`) |
| `--prompt-type TYPE` | No (repeatable) | Agent prompt type to override (e.g. `pentester`) |
| `--prompt-text TEXT` | No (paired with `--prompt-type`) | Custom prompt text for the given type |
| `--no-restore-prompts` | No | Retain prompt overrides on server after flow ends |

**Output**: Flow ID and title on success.
```
Flow created: id=42 title="Scan 10.0.0.1 for vulnerabilities"
```

---

### `messages` — Stream messages from a flow

```
pentagi messages [--verbose] [--types TYPE,...] FLOW_ID
```

| Argument / Option | Required | Description |
|---|---|---|
| `FLOW_ID` | Yes | Flow ID to subscribe to |
| `--verbose` | No | Show all message types (overrides default filtering) |
| `--types TYPE,...` | No | Comma-separated explicit type list (overrides default + verbose) |

**Default visible types** (without `--verbose`): `answer`, `report`, `ask`, `done`, `advice`  
**All types** (with `--verbose`): adds `thoughts`, `browser`, `terminal`, `search`, `file`, `input`

**Output format** (one line per message, streaming):
```
[HH:MM:SS] [TYPE] message content
```
For multi-line content (markdown, terminal output), subsequent lines are indented 2 spaces.

Ctrl-C cleanly stops the subscription.

---

### `tasks` — List tasks for a flow

```
pentagi tasks FLOW_ID
```

**Output** (table):
```
ID   STATUS     TITLE
--   --------   ----------------------------------------
1    running    Reconnaissance of target host
2    created    Enumerate web application endpoints
```

---

### `subtasks` — List subtasks for a task

```
pentagi subtasks FLOW_ID TASK_ID
```

**Output** (table):
```
ID   STATUS     TITLE
--   --------   ----------------------------------------
1    finished   Run nmap port scan
2    running    Check HTTP headers for security misconfig
```

---

### `subtask` — Show detail for a single subtask

```
pentagi subtask FLOW_ID TASK_ID SUBTASK_ID
```

**Output** (structured):
```
ID:          3
Title:       Run nmap port scan
Status:      finished
Description: Run a full TCP port scan against 10.0.0.1 and report open ports...
Result:      Open ports: 22, 80, 443, 8080
Context:     Target is a Linux host based on prior reconnaissance
```

---

### `reply` — Send input to a waiting flow

```
pentagi reply FLOW_ID INPUT
```

| Argument | Required | Description |
|---|---|---|
| `FLOW_ID` | Yes | Flow ID to reply to |
| `INPUT` | Yes | Text to send to the waiting agent |

**Output**:
```
Reply sent to flow 42.
```

---

### `stop` — Stop a running flow

```
pentagi stop FLOW_ID
```

**Output**:
```
Flow 42 stopped.
```

---

## Exit codes

| Code | Meaning |
|------|---------|
| `0` | Success |
| `1` | Runtime error (auth failure, API error, stream failure) |
| `2` | Usage error (missing required argument, unknown command) |

---

## Error output format

All errors are written to stderr:
```
Error: <descriptive message>
```
For auth failures:
```
Error: Authentication failed — check PENTAGI_API_TOKEN in .env
```
