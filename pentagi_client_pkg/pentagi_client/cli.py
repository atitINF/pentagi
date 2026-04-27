from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from typing import Optional

import click

from .client import PentAGIClient
from .config import Config
from .exceptions import PentAGIError
from .models import MessageType

_DEFAULT_TYPES = {
    MessageType.answer,
    MessageType.report,
    MessageType.ask,
    MessageType.done,
    MessageType.advice,
}
_VERBOSE_EXTRA = {
    MessageType.thoughts,
    MessageType.browser,
    MessageType.terminal,
    MessageType.search,
    MessageType.file,
    MessageType.input,
}


def _client(env: str) -> PentAGIClient:
    return PentAGIClient(Config.from_env(env))


def _err(msg: str) -> None:
    click.echo(f"Error: {msg}", err=True)


def _raw(data) -> None:
    click.echo(json.dumps(data, indent=2, default=str))


@click.group()
@click.option("--env", default=".env", show_default=True, help="Path to .env file")
@click.option("--raw", is_flag=True, default=False,
              help="Print raw JSON from the API instead of formatted output")
@click.pass_context
def cli(ctx, env: str, raw: bool) -> None:
    ctx.ensure_object(dict)
    ctx.obj["env"] = env
    ctx.obj["raw"] = raw


# ---------------------------------------------------------------------------
# start
# ---------------------------------------------------------------------------

@cli.command()
@click.argument("input")
@click.option("--provider", required=True, help="LLM provider (e.g. openai, anthropic)")
@click.option("--prompt-type", "prompt_types", multiple=True,
              help="Agent prompt type to override (repeatable)")
@click.option("--prompt-text", "prompt_texts", multiple=True,
              help="Replacement text for --prompt-type (paired, repeatable)")
@click.option("--no-restore-prompts", is_flag=True, default=False,
              help="Keep prompt overrides on server after flow ends")
@click.pass_context
def start(ctx, input: str, provider: str, prompt_types, prompt_texts, no_restore_prompts: bool):
    """Start a new AI penetration test flow."""
    if len(prompt_types) != len(prompt_texts):
        _err("--prompt-type and --prompt-text must be paired (same count)")
        sys.exit(2)

    prompt_overrides = dict(zip(prompt_types, prompt_texts)) or None

    try:
        client = _client(ctx.obj["env"])
        if ctx.obj["raw"]:
            data = client._post("/flows/", {"input": input, "provider": provider})
            _raw(data)
            return
        flow = client.start_flow(
            input=input,
            provider=provider,
            prompt_overrides=prompt_overrides,
            restore_prompts=not no_restore_prompts,
        )
        click.echo(f'Flow created: id={flow.id} title="{flow.title}"')
    except PentAGIError as exc:
        _err(str(exc))
        sys.exit(1)


# ---------------------------------------------------------------------------
# messages
# ---------------------------------------------------------------------------

@cli.command()
@click.argument("flow_id", type=int)
@click.option("--verbose", is_flag=True, default=False,
              help="Show all message types (thoughts, terminal, search, …)")
@click.option("--types", default=None,
              help="Comma-separated explicit type filter (overrides default + verbose)")
@click.option("--debug", is_flag=True, default=False,
              help="Print raw WebSocket events to stderr for troubleshooting")
@click.pass_context
def messages(ctx, flow_id: int, verbose: bool, types: Optional[str], debug: bool):
    """Stream live messages from a running flow (Ctrl-C to stop).

    If the flow is already finished or failed, falls back to showing
    historical logs (same as the 'logs' command).
    """
    if types:
        allowed = set(t.strip() for t in types.split(","))
    elif verbose:
        allowed = {t.value for t in (_DEFAULT_TYPES | _VERBOSE_EXTRA)}
    else:
        allowed = {t.value for t in _DEFAULT_TYPES}

    try:
        client = _client(ctx.obj["env"])

        flow = client.get_flow(flow_id)
        if flow.status.value in ("finished", "failed"):
            click.echo(f"Flow {flow_id} is {flow.status.value} — showing historical logs.", err=True)
            if ctx.obj["raw"]:
                _raw(client._get(f"/flows/{flow_id}/msglogs/", page=1, type="init", pageSize=-1))
                return
            all_msgs = client.get_messages(flow_id)
            filtered = [m for m in all_msgs if m.type.value in allowed]
            if not filtered:
                click.echo("No messages found.")
                return
            for msg in filtered:
                ts = (msg.created_at or datetime.now(tz=timezone.utc)).strftime("%H:%M:%S")
                lines = msg.message.splitlines() or [""]
                click.echo(f"[{ts}] [{msg.type.value}] {lines[0]}")
                for line in lines[1:]:
                    click.echo(f"  {line}")
            return

        for msg in client.messages(flow_id, types=list(allowed), debug=debug):
            if msg.type == MessageType.reconnect:
                click.echo(f"[reconnecting…]", err=True)
                continue
            ts = (msg.created_at or datetime.now(tz=timezone.utc)).strftime("%H:%M:%S")
            lines = msg.message.splitlines() or [""]
            click.echo(f"[{ts}] [{msg.type.value}] {lines[0]}")
            for line in lines[1:]:
                click.echo(f"  {line}")
    except KeyboardInterrupt:
        pass
    except PentAGIError as exc:
        _err(str(exc))
        sys.exit(1)


# ---------------------------------------------------------------------------
# logs
# ---------------------------------------------------------------------------

@cli.command()
@click.argument("flow_id", type=int)
@click.option("--verbose", is_flag=True, default=False,
              help="Show all message types including thoughts, terminal output, searches")
@click.option("--types", default=None,
              help="Comma-separated explicit type filter")
@click.option("--tail", default=0, type=int,
              help="Show only the last N messages (0 = all)")
@click.pass_context
def logs(ctx, flow_id: int, verbose: bool, types: Optional[str], tail: int):
    """Fetch historical messages for a flow from the REST API.

    Unlike 'messages', this works on finished flows and shows everything
    that already happened. Great for debugging or reviewing results.
    """
    try:
        client = _client(ctx.obj["env"])
        if ctx.obj["raw"]:
            _raw(client._get(f"/flows/{flow_id}/msglogs/", page=1, type="init", pageSize=-1))
            return
    except PentAGIError as exc:
        _err(str(exc))
        sys.exit(1)

    if types:
        allowed = set(t.strip() for t in types.split(","))
    elif verbose:
        allowed = {t.value for t in (_DEFAULT_TYPES | _VERBOSE_EXTRA)}
    else:
        allowed = {t.value for t in _DEFAULT_TYPES}

    try:
        all_msgs = client.get_messages(flow_id)
    except PentAGIError as exc:
        _err(str(exc))
        sys.exit(1)

    filtered = [m for m in all_msgs if m.type.value in allowed]

    if tail > 0:
        filtered = filtered[-tail:]

    if not filtered:
        click.echo("No messages found.")
        return

    for msg in filtered:
        ts = (msg.created_at or datetime.now(tz=timezone.utc)).strftime("%H:%M:%S")
        lines = msg.message.splitlines() or [""]
        click.echo(f"[{ts}] [{msg.type.value}] {lines[0]}")
        for line in lines[1:]:
            click.echo(f"  {line}")


# ---------------------------------------------------------------------------
# tasks
# ---------------------------------------------------------------------------

@cli.command()
@click.argument("flow_id", type=int)
@click.pass_context
def tasks(ctx, flow_id: int):
    """List tasks for a flow."""
    try:
        client = _client(ctx.obj["env"])
        if ctx.obj["raw"]:
            _raw(client._get(f"/flows/{flow_id}/tasks/", page=1, type="init", pageSize=-1))
            return
        task_list = client.get_tasks(flow_id)
    except PentAGIError as exc:
        _err(str(exc))
        sys.exit(1)

    if not task_list:
        click.echo("No tasks found.")
        return

    click.echo(f"{'ID':<6} {'STATUS':<12} TITLE")
    click.echo(f"{'--':<6} {'--------':<12} {'-----'}")
    for t in task_list:
        click.echo(f"{t.id:<6} {t.status.value:<12} {t.title}")


# ---------------------------------------------------------------------------
# subtasks
# ---------------------------------------------------------------------------

@cli.command()
@click.argument("flow_id", type=int)
@click.argument("task_id", type=int)
@click.pass_context
def subtasks(ctx, flow_id: int, task_id: int):
    """List subtasks for a task."""
    try:
        client = _client(ctx.obj["env"])
        if ctx.obj["raw"]:
            _raw(client._get(
                f"/flows/{flow_id}/tasks/{task_id}/subtasks/",
                page=1, type="init", pageSize=-1,
            ))
            return
        sub_list = client.get_subtasks(flow_id, task_id)
    except PentAGIError as exc:
        _err(str(exc))
        sys.exit(1)

    if not sub_list:
        click.echo("No subtasks found.")
        return

    click.echo(f"{'ID':<6} {'STATUS':<12} TITLE")
    click.echo(f"{'--':<6} {'--------':<12} {'-----'}")
    for s in sub_list:
        click.echo(f"{s.id:<6} {s.status.value:<12} {s.title}")


# ---------------------------------------------------------------------------
# subtask
# ---------------------------------------------------------------------------

@cli.command()
@click.argument("flow_id", type=int)
@click.argument("task_id", type=int)
@click.argument("subtask_id", type=int)
@click.pass_context
def subtask(ctx, flow_id: int, task_id: int, subtask_id: int):
    """Show detail for a single subtask."""
    try:
        client = _client(ctx.obj["env"])
        if ctx.obj["raw"]:
            _raw(client._get(f"/flows/{flow_id}/tasks/{task_id}/subtasks/{subtask_id}"))
            return
        s = client.get_subtask(flow_id, task_id, subtask_id)
    except PentAGIError as exc:
        _err(str(exc))
        sys.exit(1)

    click.echo(f"ID:          {s.id}")
    click.echo(f"Title:       {s.title}")
    click.echo(f"Status:      {s.status.value}")
    click.echo(f"Description: {s.description}")
    click.echo(f"Result:      {s.result or '—'}")
    click.echo(f"Context:     {s.context or '—'}")


# ---------------------------------------------------------------------------
# allsubtasks
# ---------------------------------------------------------------------------

@cli.command()
@click.argument("flow_id", type=int)
@click.pass_context
def allsubtasks(ctx, flow_id: int):
    """List every subtask across all tasks for a flow."""
    try:
        client = _client(ctx.obj["env"])
        if ctx.obj["raw"]:
            _raw(client._get(f"/flows/{flow_id}/subtasks/", page=1, type="init", pageSize=-1))
            return
        sub_list = client.get_all_subtasks(flow_id)
    except PentAGIError as exc:
        _err(str(exc))
        sys.exit(1)

    if not sub_list:
        click.echo("No subtasks found.")
        return

    for s in sub_list:
        click.echo(f"--- Task {s.task_id} / Subtask {s.id} ---")
        click.echo(f"  Title:       {s.title}")
        click.echo(f"  Status:      {s.status.value}")
        click.echo(f"  Description: {s.description}")
        click.echo(f"  Result:      {s.result or '—'}")
        click.echo(f"  Context:     {s.context or '—'}")
        click.echo("")


# ---------------------------------------------------------------------------
# reply
# ---------------------------------------------------------------------------

@cli.command()
@click.argument("flow_id", type=int)
@click.argument("input")
@click.pass_context
def reply(ctx, flow_id: int, input: str):
    """Send a reply to a flow that is waiting for user input."""
    try:
        client = _client(ctx.obj["env"])
        client.reply_to_flow(flow_id, input)
        click.echo(f"Reply sent to flow {flow_id}.")
    except PentAGIError as exc:
        _err(str(exc))
        sys.exit(1)


# ---------------------------------------------------------------------------
# chat
# ---------------------------------------------------------------------------

@cli.command()
@click.argument("flow_id", type=int)
@click.argument("message")
@click.option("--provider", default="openai", show_default=True,
              help="LLM provider for the assistant")
@click.option("--no-agents", is_flag=True, default=False,
              help="Disable multi-agent mode (assistant only)")
@click.option("--verbose", is_flag=True, default=False,
              help="Show all message types including thoughts, searches, and tool output")
@click.option("--debug", is_flag=True, default=False,
              help="Print raw WebSocket events to stderr for troubleshooting")
@click.pass_context
def chat(ctx, flow_id: int, message: str, provider: str, no_agents: bool, verbose: bool, debug: bool):
    """Start an interactive chat with an AI assistant about a running flow.

    The assistant has full context of the flow's tasks, findings, and logs.
    Type your message as an argument to start, then keep chatting interactively.
    Press Ctrl-C or type 'exit' / 'quit' to end the session.

    Example:

        pentagi chat 42 "What vulnerabilities have been found so far?"
    """
    try:
        client = _client(ctx.obj["env"])
        assistant = client.create_assistant(
            flow_id=flow_id,
            input=message,
            provider=provider,
            use_agents=not no_agents,
        )
    except PentAGIError as exc:
        _err(str(exc))
        sys.exit(1)

    click.echo(f"Assistant {assistant.id} started. Ctrl-C or type 'exit' to quit.\n")

    _DEFAULT_ASSISTANT_TYPES = {
        MessageType.answer, MessageType.report, MessageType.ask,
        MessageType.advice, MessageType.done,
    }
    _VERBOSE_ASSISTANT_TYPES = _DEFAULT_ASSISTANT_TYPES | _VERBOSE_EXTRA

    allowed_types = _VERBOSE_ASSISTANT_TYPES if verbose else _DEFAULT_ASSISTANT_TYPES

    def _print_msg(msg) -> bool:
        """Print one assistant log entry. Returns True if this was a done signal."""
        if msg.type not in allowed_types:
            return False
        if msg.type == MessageType.done:
            return True
        ts = (msg.created_at or datetime.now(tz=timezone.utc)).strftime("%H:%M:%S")
        if msg.type in _DEFAULT_ASSISTANT_TYPES:
            if msg.append_part:
                click.echo(msg.message, nl=False)
            else:
                click.echo(f"\nAssistant: {msg.message}")
        else:
            lines = msg.message.splitlines() or [""]
            click.echo(f"[{ts}] [{msg.type.value}] {lines[0]}", err=True)
            for line in lines[1:]:
                click.echo(f"  {line}", err=True)
        return False

    def _stream_until_done(seen_ids: set):
        """Print assistant messages until a 'done' arrives or stream ends.

        Starts the WebSocket subscription first (background thread), then
        fetches REST history to catch any messages that arrived before the
        subscription was active, then drains new messages from the WS.
        Deduplicates by message ID across all sources and turns.
        """
        # 1. Open WS immediately so its background thread starts subscribing
        #    while we do the history fetch in parallel.
        stream = client.open_assistant_stream(flow_id, assistant.id, debug=debug)
        try:
            # 2. Fetch history — catches messages that arrived before WS was ready.
            try:
                for msg in client.get_assistant_logs(flow_id, assistant.id):
                    if msg.id in seen_ids:
                        continue
                    if msg.id is not None:
                        seen_ids.add(msg.id)
                    if _print_msg(msg):
                        return  # already done from history
            except PentAGIError:
                pass  # best-effort

            # 3. Drain WS for messages that arrived after or during the history fetch.
            for msg in stream:
                if msg.type == MessageType.reconnect:
                    click.echo(f"\n[reconnecting…]", err=True)
                    continue
                if msg.id in seen_ids:
                    continue
                if msg.id is not None:
                    seen_ids.add(msg.id)
                if _print_msg(msg):
                    break

            # 4. Final history poll — catches anything that slipped through
            #    between the first fetch and the WS closing/timing out.
            try:
                for msg in client.get_assistant_logs(flow_id, assistant.id):
                    if msg.id in seen_ids:
                        continue
                    if msg.id is not None:
                        seen_ids.add(msg.id)
                    _print_msg(msg)
            except PentAGIError:
                pass
        except PentAGIError as exc:
            _err(str(exc))
        finally:
            stream.close()

    seen_ids: set = set()
    _stream_until_done(seen_ids)

    while True:
        try:
            click.echo("")
            user_input = click.prompt("You", prompt_suffix="> ")
        except (click.Abort, EOFError, KeyboardInterrupt):
            break

        if user_input.strip().lower() in ("exit", "quit", "q"):
            break

        try:
            client.reply_to_assistant(flow_id, assistant.id, user_input)
        except PentAGIError as exc:
            _err(str(exc))
            break

        _stream_until_done(seen_ids)

    try:
        client.stop_assistant(flow_id, assistant.id)
    except PentAGIError:
        pass

    click.echo("\nChat session ended.")


# ---------------------------------------------------------------------------
# ask  (non-streaming chat via REST polling)
# ---------------------------------------------------------------------------

@cli.command()
@click.argument("flow_id", type=int)
@click.argument("message")
@click.option("--provider", default="openai", show_default=True,
              help="LLM provider for the assistant")
@click.option("--no-agents", is_flag=True, default=False,
              help="Disable multi-agent mode (assistant only)")
@click.option("--timeout", default=120, type=int, show_default=True,
              help="Seconds to wait for each response before giving up")
@click.option("--poll", default=2, type=float, show_default=True,
              help="Polling interval in seconds")
@click.pass_context
def ask(ctx, flow_id: int, message: str, provider: str, no_agents: bool,
        timeout: int, poll: float):
    """Non-streaming chat: polls the REST API instead of using WebSocket.

    More reliable than 'chat' when the WebSocket connection is flaky.
    Creates an assistant, waits for the response via polling, then lets
    you keep asking follow-up questions. Ctrl-C or 'exit' to quit.

    Example:

        pentagi ask 42 "What vulnerabilities have been found?" --provider gemini
    """
    try:
        client = _client(ctx.obj["env"])
        assistant = client.create_assistant(
            flow_id=flow_id,
            input=message,
            provider=provider,
            use_agents=not no_agents,
        )
    except PentAGIError as exc:
        _err(str(exc))
        sys.exit(1)

    click.echo(f"Assistant {assistant.id} ready. Ctrl-C or type 'exit' to quit.\n")

    seen_ids: set = set()

    def _poll_and_print():
        click.echo("Waiting for response…", err=True)
        new_msgs = client.wait_for_assistant_response(
            flow_id, assistant.id, seen_ids,
            timeout=timeout, poll_interval=poll,
        )
        if not new_msgs:
            click.echo("(no response within timeout)", err=True)
            return
        for msg in new_msgs:
            if msg.id is not None:
                seen_ids.add(msg.id)
            if msg.type.value in ("input", "done"):
                continue
            ts = (msg.created_at or datetime.now(tz=timezone.utc)).strftime("%H:%M:%S")
            if msg.type.value in ("answer", "report"):
                click.echo(f"\nAssistant: {msg.message}")
            else:
                lines = msg.message.splitlines() or [""]
                click.echo(f"[{ts}] [{msg.type.value}] {lines[0]}")
                for line in lines[1:]:
                    click.echo(f"  {line}")

    _poll_and_print()

    while True:
        try:
            click.echo("")
            user_input = click.prompt("You", prompt_suffix="> ")
        except (click.Abort, EOFError, KeyboardInterrupt):
            break

        if user_input.strip().lower() in ("exit", "quit", "q"):
            break

        try:
            client.reply_to_assistant(flow_id, assistant.id, user_input)
        except PentAGIError as exc:
            _err(str(exc))
            break

        _poll_and_print()

    try:
        client.stop_assistant(flow_id, assistant.id)
    except PentAGIError:
        pass

    click.echo("\nSession ended.")


# ---------------------------------------------------------------------------
# assistlogs  (non-streaming, all assistant conversations for a flow)
# ---------------------------------------------------------------------------

@cli.command()
@click.argument("flow_id", type=int)
@click.option("--assistant-id", "filter_assistant_id", default=None, type=int,
              help="Only show logs for a specific assistant session")
@click.option("--verbose", is_flag=True, default=False,
              help="Show all message types including thoughts, searches, tool output")
@click.pass_context
def assistlogs(ctx, flow_id: int, filter_assistant_id: Optional[int], verbose: bool):
    """Show all previous assistant conversations for a flow (REST, non-streaming).

    Conversations are grouped by assistant session ID and printed in order.
    Use --assistant-id to filter to a single session.

    Example:

        pentagi assistlogs 42
        pentagi assistlogs 42 --assistant-id 7
    """
    try:
        client = _client(ctx.obj["env"])
        if ctx.obj["raw"]:
            _raw(client._get(f"/flows/{flow_id}/assistantlogs/", page=1, type="init", pageSize=-1))
            return
        all_logs = client.get_all_assistant_logs(flow_id)
    except PentAGIError as exc:
        _err(str(exc))
        sys.exit(1)

    if not all_logs:
        click.echo("No assistant logs found.")
        return

    allowed_types = (_DEFAULT_TYPES | _VERBOSE_EXTRA) if verbose else _DEFAULT_TYPES

    # Group by assistant_id preserving insertion order
    sessions: dict = {}
    for log in all_logs:
        aid = log.assistant_id
        if filter_assistant_id is not None and aid != filter_assistant_id:
            continue
        if log.type not in allowed_types:
            continue
        sessions.setdefault(aid, []).append(log)

    if not sessions:
        click.echo("No matching assistant logs found.")
        return

    for aid, msgs in sessions.items():
        label = f"Assistant session {aid}" if aid is not None else "Assistant session (unknown)"
        click.echo(f"\n{'='*60}")
        click.echo(f"  {label}")
        click.echo(f"{'='*60}")
        for msg in msgs:
            if msg.type == MessageType.done:
                click.echo("  [done]")
                continue
            ts = (msg.created_at or datetime.now(tz=timezone.utc)).strftime("%H:%M:%S")
            prefix = "  Assistant" if msg.type.value in ("answer", "report") else f"  [{msg.type.value}]"
            lines = msg.message.splitlines() or [""]
            click.echo(f"  [{ts}] {prefix}: {lines[0]}")
            for line in lines[1:]:
                click.echo(f"    {line}")
        click.echo("")


# ---------------------------------------------------------------------------
# usage
# ---------------------------------------------------------------------------

def _fmt_tokens(n: int) -> str:
    if n >= 1_000_000:
        return f"{n / 1_000_000:.2f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}K"
    return str(n)


def _fmt_cost(v: float) -> str:
    return f"${v:.4f}"


def _fmt_duration(seconds: float) -> str:
    if seconds >= 3600:
        return f"{seconds / 3600:.1f}h"
    if seconds >= 60:
        return f"{seconds / 60:.1f}m"
    return f"{seconds:.1f}s"


def _print_usage_stats(label: str, s: dict) -> None:
    tokens_in  = s.get("total_usage_in", 0)
    tokens_out = s.get("total_usage_out", 0)
    cache_in   = s.get("total_usage_cache_in", 0)
    cache_out  = s.get("total_usage_cache_out", 0)
    cost_in    = s.get("total_usage_cost_in", 0.0)
    cost_out   = s.get("total_usage_cost_out", 0.0)
    click.echo(f"  {label}")
    click.echo(f"    Tokens in:    {_fmt_tokens(tokens_in):>10}   cost: {_fmt_cost(cost_in)}")
    click.echo(f"    Tokens out:   {_fmt_tokens(tokens_out):>10}   cost: {_fmt_cost(cost_out)}")
    click.echo(f"    Cache in:     {_fmt_tokens(cache_in):>10}")
    click.echo(f"    Cache out:    {_fmt_tokens(cache_out):>10}")
    click.echo(f"    Total cost:   {_fmt_cost(cost_in + cost_out):>10}")


@cli.command()
@click.option("--flow-id", default=None, type=int,
              help="Show usage for a specific flow instead of the whole account")
@click.option("--period", default=None,
              type=click.Choice(["week", "month", "quarter"], case_sensitive=False),
              help="Show time-series breakdown for the given period (system-wide only)")
@click.option("--by-model", is_flag=True, default=False,
              help="Include per-model token breakdown")
@click.option("--by-agent", is_flag=True, default=False,
              help="Include per-agent-type token breakdown")
@click.option("--tools", "show_tools", is_flag=True, default=False,
              help="Include tool-call stats")
@click.pass_context
def usage(ctx, flow_id: Optional[int], period: Optional[str],
          by_model: bool, by_agent: bool, show_tools: bool):
    """Show token usage and cost statistics (like the Dashboard screen).

    Without options prints account-wide totals. Use --flow-id for a single
    flow, or --period for a daily time-series breakdown.

    Examples:

        pentagi usage
        pentagi usage --flow-id 42
        pentagi usage --period month --by-model
        pentagi --raw usage
    """
    try:
        client = _client(ctx.obj["env"])

        if ctx.obj["raw"]:
            if flow_id is not None:
                _raw(client._get(f"/flows/{flow_id}/usage/"))
            elif period:
                _raw(client._get(f"/usage/{period}"))
            else:
                _raw(client._get("/usage/"))
            return

        if flow_id is not None:
            data = client.get_flow_usage(flow_id)
            _print_flow_usage(data, flow_id, by_agent=by_agent, show_tools=show_tools)
        elif period:
            data = client.get_period_usage(period)
            _print_period_usage(data, period)
        else:
            data = client.get_usage()
            _print_system_usage(data, by_model=by_model, by_agent=by_agent, show_tools=show_tools)

    except (PentAGIError, ValueError) as exc:
        _err(str(exc))
        sys.exit(1)


def _print_system_usage(data: dict, by_model: bool, by_agent: bool, show_tools: bool) -> None:
    click.echo("\n=== Account Usage ===\n")

    total = data.get("usage_stats_total") or {}
    _print_usage_stats("Total", total)

    flows = data.get("flows_stats_total") or {}
    click.echo(f"\n  Flows:      {flows.get('total_flows_count', 0)}")
    click.echo(f"  Tasks:      {flows.get('total_tasks_count', 0)}")
    click.echo(f"  Subtasks:   {flows.get('total_subtasks_count', 0)}")
    click.echo(f"  Assistants: {flows.get('total_assistants_count', 0)}")

    by_provider = data.get("usage_stats_by_provider") or []
    if by_provider:
        click.echo("\n--- By Provider ---")
        for entry in by_provider:
            _print_usage_stats(entry.get("provider", "?"), entry.get("stats") or {})

    if by_model:
        by_model_data = data.get("usage_stats_by_model") or []
        if by_model_data:
            click.echo("\n--- By Model ---")
            for entry in by_model_data:
                label = f"{entry.get('provider', '?')} / {entry.get('model', '?')}"
                _print_usage_stats(label, entry.get("stats") or {})

    if by_agent:
        by_agent_data = data.get("usage_stats_by_agent_type") or []
        if by_agent_data:
            click.echo("\n--- By Agent Type ---")
            for entry in by_agent_data:
                _print_usage_stats(entry.get("agent_type", "?"), entry.get("stats") or {})

    if show_tools:
        tc = data.get("toolcalls_stats_total") or {}
        click.echo(f"\n--- Tool Calls ---")
        click.echo(f"  Total calls:    {tc.get('total_count', 0)}")
        click.echo(f"  Total duration: {_fmt_duration(tc.get('total_duration_seconds', 0.0))}")
        by_fn = data.get("toolcalls_stats_by_function") or []
        if by_fn:
            click.echo(f"\n  {'Tool':<35} {'Calls':>6} {'Total':>8} {'Avg':>8}  Agent")
            click.echo(f"  {'-'*35} {'------':>6} {'--------':>8} {'--------':>8}  -----")
            for fn in by_fn:
                agent_mark = "yes" if fn.get("is_agent") else ""
                click.echo(
                    f"  {fn.get('function_name', '?'):<35} "
                    f"{fn.get('total_count', 0):>6} "
                    f"{_fmt_duration(fn.get('total_duration_seconds', 0.0)):>8} "
                    f"{_fmt_duration(fn.get('avg_duration_seconds', 0.0)):>8}  {agent_mark}"
                )


def _print_flow_usage(data: dict, flow_id: int, by_agent: bool, show_tools: bool) -> None:
    click.echo(f"\n=== Flow {flow_id} Usage ===\n")

    flow_stats = data.get("usage_stats_by_flow") or {}
    _print_usage_stats("Total", flow_stats)

    struct = data.get("flow_stats_by_flow") or {}
    click.echo(f"\n  Tasks:      {struct.get('total_tasks_count', 0)}")
    click.echo(f"  Subtasks:   {struct.get('total_subtasks_count', 0)}")
    click.echo(f"  Assistants: {struct.get('total_assistants_count', 0)}")

    if by_agent:
        by_agent_data = data.get("usage_stats_by_agent_type_for_flow") or []
        if by_agent_data:
            click.echo("\n--- By Agent Type ---")
            for entry in by_agent_data:
                _print_usage_stats(entry.get("agent_type", "?"), entry.get("stats") or {})

    if show_tools:
        tc = data.get("toolcalls_stats_by_flow") or {}
        click.echo(f"\n--- Tool Calls ---")
        click.echo(f"  Total calls:    {tc.get('total_count', 0)}")
        click.echo(f"  Total duration: {_fmt_duration(tc.get('total_duration_seconds', 0.0))}")
        by_fn = data.get("toolcalls_stats_by_function_for_flow") or []
        if by_fn:
            click.echo(f"\n  {'Tool':<35} {'Calls':>6} {'Total':>8} {'Avg':>8}  Agent")
            click.echo(f"  {'-'*35} {'------':>6} {'--------':>8} {'--------':>8}  -----")
            for fn in by_fn:
                agent_mark = "yes" if fn.get("is_agent") else ""
                click.echo(
                    f"  {fn.get('function_name', '?'):<35} "
                    f"{fn.get('total_count', 0):>6} "
                    f"{_fmt_duration(fn.get('total_duration_seconds', 0.0)):>8} "
                    f"{_fmt_duration(fn.get('avg_duration_seconds', 0.0)):>8}  {agent_mark}"
                )


def _print_period_usage(data: dict, period: str) -> None:
    click.echo(f"\n=== Usage by Day ({period}) ===\n")
    daily = data.get("usage_stats_by_period") or []
    if not daily:
        click.echo("  No data for this period.")
        return
    click.echo(f"  {'Date':<12} {'In':>10} {'Out':>10} {'CacheIn':>10} {'Cost':>10}")
    click.echo(f"  {'-'*12} {'----------':>10} {'----------':>10} {'----------':>10} {'----------':>10}")
    for entry in daily:
        date = (entry.get("date") or "")[:10]
        s = entry.get("stats") or {}
        click.echo(
            f"  {date:<12} "
            f"{_fmt_tokens(s.get('total_usage_in', 0)):>10} "
            f"{_fmt_tokens(s.get('total_usage_out', 0)):>10} "
            f"{_fmt_tokens(s.get('total_usage_cache_in', 0)):>10} "
            f"{_fmt_cost(s.get('total_usage_cost_in', 0.0) + s.get('total_usage_cost_out', 0.0)):>10}"
        )


# ---------------------------------------------------------------------------
# agentlogs
# ---------------------------------------------------------------------------

@cli.command()
@click.argument("flow_id", type=int)
@click.option("--task-id", default=None, type=int, help="Filter to a specific task ID")
@click.option("--subtask-id", default=None, type=int, help="Filter to a specific subtask ID")
@click.option("--tail", default=0, type=int, help="Show only the last N entries (0 = all)")
@click.option("--show-result/--no-result", default=True, show_default=True,
              help="Include the agent result text")
@click.pass_context
def agentlogs(ctx, flow_id: int, task_id: Optional[int], subtask_id: Optional[int],
              tail: int, show_result: bool):
    """Show agent interaction logs for a flow.

    Each entry records one agent-to-agent call: which agent (initiator) delegated
    a task to which agent (executor), what the task was, and what came back.

    Example:

        pentagi agentlogs 42
        pentagi agentlogs 42 --subtask-id 5
        pentagi agentlogs 42 --tail 20 --no-result
        pentagi --raw agentlogs 42
    """
    try:
        client = _client(ctx.obj["env"])
        if ctx.obj["raw"]:
            _raw(client._get(f"/flows/{flow_id}/agentlogs/", page=1, type="init", pageSize=-1))
            return
        entries = client.get_agent_logs(flow_id, task_id=task_id, subtask_id=subtask_id)
    except PentAGIError as exc:
        _err(str(exc))
        sys.exit(1)

    if not entries:
        click.echo("No agent logs found.")
        return

    if tail > 0:
        entries = entries[-tail:]

    for entry in entries:
        ts = (entry.created_at or datetime.now(tz=timezone.utc)).strftime("%H:%M:%S")
        scope = ""
        if entry.task_id is not None:
            scope = f" task={entry.task_id}"
            if entry.subtask_id is not None:
                scope += f"/sub={entry.subtask_id}"
        click.echo(
            f"[{ts}]{scope} {entry.initiator} → {entry.executor}"
        )
        task_lines = entry.task.splitlines()
        click.echo(f"  Task: {task_lines[0]}")
        for line in task_lines[1:]:
            click.echo(f"        {line}")
        if show_result and entry.result:
            result_lines = entry.result.splitlines()
            click.echo(f"  Result: {result_lines[0]}")
            for line in result_lines[1:]:
                click.echo(f"          {line}")
        click.echo("")


# ---------------------------------------------------------------------------
# findings  (JSON Output subtask extraction)
# ---------------------------------------------------------------------------

@cli.command()
@click.argument("flow_id", type=int)
@click.option("--compact", is_flag=True, default=False,
              help="Output compact JSON (no pretty-print)")
@click.option("--subtask-name", default="JSON Output", show_default=True,
              help="Exact subtask title to search for")
@click.pass_context
def findings(ctx, flow_id: int, compact: bool, subtask_name: str):
    """Extract structured findings JSON from the final 'JSON Output' subtask.

    Searches all subtasks for the last one matching the subtask name (default:
    'JSON Output'), parses its result field as JSON, and prints it.
    If the result contains surrounding text the JSON array is extracted
    automatically.

    Example:

        pentagi findings 42
        pentagi findings 42 --compact
        pentagi --raw findings 42
    """
    import re as _re

    try:
        client = _client(ctx.obj["env"])
        if ctx.obj["raw"]:
            _raw(client._get(f"/flows/{flow_id}/subtasks/", page=1, type="init", pageSize=-1))
            return
        all_subs = client.get_all_subtasks(flow_id)
    except PentAGIError as exc:
        _err(str(exc))
        sys.exit(1)

    # Find the last subtask whose title exactly matches the expected name.
    json_subtask = None
    for s in reversed(all_subs):
        if s.title.strip() == subtask_name:
            json_subtask = s
            break

    if json_subtask is None:
        _err(f"No '{subtask_name}' subtask found for flow {flow_id}.")
        click.echo(f"Available subtask titles:", err=True)
        for s in all_subs:
            click.echo(f"  [{s.id}] {s.title}", err=True)
        sys.exit(1)

    raw_result = (json_subtask.result or "").strip()

    if not raw_result:
        click.echo("[]")
        return

    # Try direct parse first; if that fails, extract first [...] block.
    data = None
    try:
        data = json.loads(raw_result)
    except json.JSONDecodeError:
        match = _re.search(r"\[.*\]", raw_result, _re.DOTALL)
        if match:
            try:
                data = json.loads(match.group(0))
            except json.JSONDecodeError:
                pass

    if data is None:
        _err("Could not parse JSON from the subtask result. Raw content:")
        click.echo(raw_result)
        sys.exit(1)

    indent = None if compact else 2
    click.echo(json.dumps(data, indent=indent))


# ---------------------------------------------------------------------------
# stop
# ---------------------------------------------------------------------------

@cli.command()
@click.argument("flow_id", type=int)
@click.pass_context
def stop(ctx, flow_id: int):
    """Stop a running or waiting flow immediately."""
    try:
        client = _client(ctx.obj["env"])
        client.stop_flow(flow_id)
        click.echo(f"Flow {flow_id} stopped.")
    except PentAGIError as exc:
        _err(str(exc))
        sys.exit(1)
