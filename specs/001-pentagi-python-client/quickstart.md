# Quickstart: PentAGI Python Client

## Prerequisites

- Python 3.9+
- A running PentAGI instance
- A PentAGI API token (create one at `https://<your-host>/api/v1/tokens`)

---

## Install

```bash
cd pentagi_client_pkg/        # the generated package directory
pip install -e .
```

---

## Configure

Create a `.env` file in your working directory:

```ini
PENTAGI_BASE_URL=https://localhost:8443
PENTAGI_API_TOKEN=your-token-here

# TLS (leave VERIFY_SSL=false for default self-signed Docker install)
PENTAGI_VERIFY_SSL=false
# PENTAGI_CA_CERT=/path/to/ca.pem   # only needed when VERIFY_SSL=true

# Optional
PENTAGI_WS_MAX_RETRIES=3
```

---

## CLI usage

### Start a pentest

```bash
pentagi start --provider openai "Perform a full recon and vulnerability scan on 10.0.0.1"
# Flow created: id=42 title="Perform a full recon and vulnerability scan on 10.0.0.1"
```

### Start with a custom prompt override

```bash
pentagi start \
  --provider openai \
  --prompt-type pentester \
  --prompt-text "Focus only on OWASP Top 10 web vulnerabilities. Skip network-layer attacks." \
  "Assess the web application at http://10.0.0.1:8080"
```

### Stream live messages

```bash
pentagi messages 42
# [14:02:01] [answer] Starting reconnaissance on 10.0.0.1...
# [14:02:08] [report] Open ports: 22, 80, 443
# [14:03:15] [ask] Should I proceed with exploitation of port 80?
```

```bash
pentagi messages 42 --verbose    # include thoughts, terminal output, search results
```

### Respond to a question

```bash
pentagi reply 42 "Yes, proceed with port 80 only"
```

### List tasks and subtasks

```bash
pentagi tasks 42
pentagi subtasks 42 1
pentagi subtask 42 1 2
```

### Stop a flow

```bash
pentagi stop 42
```

---

## Library usage

```python
from pentagi_client import PentAGIClient

client = PentAGIClient()  # reads .env automatically

# Start a flow with a custom prompt
flow = client.start_flow(
    input="Scan 10.0.0.1 for open ports and web vulnerabilities",
    provider="openai",
    prompt_overrides={"pentester": "Focus on web application attacks only."},
    restore_prompts=True,
)
print(f"Flow {flow.id}: {flow.status}")

# Stream messages, respond to questions
for msg in client.messages(flow.id):
    print(f"[{msg.type}] {msg.message}")
    if msg.type == "ask":
        client.reply_to_flow(flow.id, "Yes, continue")
    if msg.type == "done":
        break

# Inspect tasks
tasks = client.get_tasks(flow.id)
for task in tasks:
    print(f"  Task {task.id}: {task.title} [{task.status}]")
    for sub in client.get_subtasks(flow.id, task.id):
        print(f"    Subtask {sub.id}: {sub.title} [{sub.status}]")

# Stop if needed
client.stop_flow(flow.id)
```
