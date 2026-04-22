from __future__ import annotations

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


@click.group()
@click.option("--env", default=".env", show_default=True, help="Path to .env file")
@click.pass_context
def cli(ctx, env: str) -> None:
    ctx.ensure_object(dict)
    ctx.obj["env"] = env


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
@click.pass_context
def messages(ctx, flow_id: int, verbose: bool, types: Optional[str]):
    """Stream live messages from a running flow (Ctrl-C to stop)."""
    if types:
        allowed = set(t.strip() for t in types.split(","))
    elif verbose:
        allowed = {t.value for t in (_DEFAULT_TYPES | _VERBOSE_EXTRA)}
    else:
        allowed = {t.value for t in _DEFAULT_TYPES}

    try:
        client = _client(ctx.obj["env"])
        for msg in client.messages(flow_id, types=list(allowed)):
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
# tasks
# ---------------------------------------------------------------------------

@cli.command()
@click.argument("flow_id", type=int)
@click.pass_context
def tasks(ctx, flow_id: int):
    """List tasks for a flow."""
    try:
        client = _client(ctx.obj["env"])
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
