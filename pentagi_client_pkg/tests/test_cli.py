from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from pentagi_client.cli import cli
from pentagi_client.exceptions import AuthError, PentAGIError
from pentagi_client.models import Flow, FlowStatus, Task, Subtask, MessageLog, MessageType, ResultFormat
from datetime import datetime, timezone


def _flow(flow_id=42):
    return Flow(
        id=flow_id, title="Test flow", status=FlowStatus.created,
        provider="openai",
        created_at=datetime.now(tz=timezone.utc),
        updated_at=datetime.now(tz=timezone.utc),
    )


def _task(task_id=1):
    return Task(
        id=task_id, flow_id=42, title="Recon", status=FlowStatus.running,
        input="scan host", result=None,
        created_at=datetime.now(tz=timezone.utc),
        updated_at=datetime.now(tz=timezone.utc),
    )


def _subtask(sub_id=2):
    return Subtask(
        id=sub_id, task_id=1, title="nmap", description="scan ports",
        status=FlowStatus.finished, result="22,80", context="linux",
        created_at=datetime.now(tz=timezone.utc),
        updated_at=datetime.now(tz=timezone.utc),
    )


def _msg(msg_type="answer", text="hello"):
    return MessageLog(
        id=1, flow_id=42, task_id=None, subtask_id=None,
        type=MessageType(msg_type), message=text,
        result=None, thinking=None,
        result_format=ResultFormat.plain,
        created_at=datetime.now(tz=timezone.utc),
    )


runner = CliRunner()


def _mock_client(method_results: dict):
    """Return a MagicMock client with given method return values / side effects."""
    mock = MagicMock()
    for method, value in method_results.items():
        if isinstance(value, Exception):
            getattr(mock, method).side_effect = value
        else:
            getattr(mock, method).return_value = value
    return mock


# ---------------------------------------------------------------------------
# start
# ---------------------------------------------------------------------------

def test_start_missing_provider():
    result = runner.invoke(cli, ["start", "Do a scan"])
    assert result.exit_code == 2


def test_start_success():
    client = _mock_client({"start_flow": _flow()})
    with patch("pentagi_client.cli._client", return_value=client):
        result = runner.invoke(cli, ["start", "--provider", "openai", "Scan host"])
    assert result.exit_code == 0
    assert "42" in result.output


def test_start_auth_error_exits_1():
    client = _mock_client({"start_flow": AuthError("bad token")})
    with patch("pentagi_client.cli._client", return_value=client):
        result = runner.invoke(cli, ["start", "--provider", "openai", "scan"])
    assert result.exit_code == 1
    assert "Error" in result.output


def test_start_with_prompt_overrides():
    client = _mock_client({"start_flow": _flow()})
    with patch("pentagi_client.cli._client", return_value=client):
        result = runner.invoke(cli, [
            "start", "--provider", "openai",
            "--prompt-type", "pentester", "--prompt-text", "Focus on web",
            "Scan host",
        ])
    assert result.exit_code == 0
    call_kwargs = client.start_flow.call_args.kwargs
    assert call_kwargs.get("prompt_overrides") == {"pentester": "Focus on web"}


def test_start_mismatched_prompt_pairs_exits_nonzero():
    client = MagicMock()
    with patch("pentagi_client.cli._client", return_value=client):
        result = runner.invoke(cli, [
            "start", "--provider", "openai",
            "--prompt-type", "pentester",
            "Scan host",
        ])
    assert result.exit_code != 0


# ---------------------------------------------------------------------------
# messages
# ---------------------------------------------------------------------------

def test_messages_default_filter():
    msgs = [_msg("answer", "hi"), _msg("thoughts", "internal"), _msg("done", "end")]
    client = _mock_client({"messages": iter(msgs)})
    with patch("pentagi_client.cli._client", return_value=client):
        result = runner.invoke(cli, ["messages", "42"])
    assert result.exit_code == 0


def test_messages_verbose_passes_all_types():
    client = _mock_client({"messages": iter([])})
    with patch("pentagi_client.cli._client", return_value=client):
        runner.invoke(cli, ["messages", "--verbose", "42"])
    call_args = client.messages.call_args
    passed_types = set(call_args.args[1] if len(call_args.args) > 1
                       else call_args.kwargs.get("types", []))
    assert "thoughts" in passed_types
    assert "answer" in passed_types


def test_messages_custom_types():
    client = _mock_client({"messages": iter([])})
    with patch("pentagi_client.cli._client", return_value=client):
        runner.invoke(cli, ["messages", "--types", "answer,done", "42"])
    call_args = client.messages.call_args
    passed_types = set(call_args.args[1] if len(call_args.args) > 1
                       else call_args.kwargs.get("types", []))
    assert passed_types == {"answer", "done"}


# ---------------------------------------------------------------------------
# tasks / subtasks / subtask
# ---------------------------------------------------------------------------

def test_tasks_command():
    client = _mock_client({"get_tasks": [_task()]})
    with patch("pentagi_client.cli._client", return_value=client):
        result = runner.invoke(cli, ["tasks", "42"])
    assert result.exit_code == 0
    assert "Recon" in result.output


def test_subtasks_command():
    client = _mock_client({"get_subtasks": [_subtask()]})
    with patch("pentagi_client.cli._client", return_value=client):
        result = runner.invoke(cli, ["subtasks", "42", "1"])
    assert result.exit_code == 0
    assert "nmap" in result.output


def test_subtask_command():
    client = _mock_client({"get_subtask": _subtask()})
    with patch("pentagi_client.cli._client", return_value=client):
        result = runner.invoke(cli, ["subtask", "42", "1", "2"])
    assert result.exit_code == 0
    assert "scan ports" in result.output
    assert "22,80" in result.output


# ---------------------------------------------------------------------------
# reply / stop
# ---------------------------------------------------------------------------

def test_reply_command():
    client = _mock_client({"reply_to_flow": None})
    with patch("pentagi_client.cli._client", return_value=client):
        result = runner.invoke(cli, ["reply", "42", "proceed"])
    assert result.exit_code == 0
    assert "42" in result.output


def test_stop_command():
    client = _mock_client({"stop_flow": None})
    with patch("pentagi_client.cli._client", return_value=client):
        result = runner.invoke(cli, ["stop", "42"])
    assert result.exit_code == 0
    assert "42" in result.output


def test_stop_pentagi_error_exits_1():
    client = _mock_client({"stop_flow": PentAGIError("server down")})
    with patch("pentagi_client.cli._client", return_value=client):
        result = runner.invoke(cli, ["stop", "42"])
    assert result.exit_code == 1
