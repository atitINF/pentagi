import json
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
import responses as resp_mock

from pentagi_client.client import PentAGIClient
from pentagi_client.config import Config
from pentagi_client.exceptions import APIError, AuthError, StreamError
from pentagi_client.models import FlowStatus, MessageLog, MessageType, Task, Subtask


def _cfg():
    return Config(base_url="https://pentagi.local", api_token="testtoken", verify_ssl=False)


def _client():
    return PentAGIClient(config=_cfg())


FLOW_DICT = {
    "id": 42,
    "title": "Scan 10.0.0.1",
    "status": "created",
    "model_provider_type": "openai",
    "created_at": "2026-04-22T12:00:00Z",
    "updated_at": "2026-04-22T12:00:00Z",
}

TASK_DICT = {
    "id": 1,
    "flow_id": 42,
    "title": "Reconnaissance",
    "status": "running",
    "input": "Scan the host",
    "result": None,
    "subtasks": [],
    "created_at": "2026-04-22T12:00:00Z",
    "updated_at": "2026-04-22T12:00:00Z",
}

SUBTASK_DICT = {
    "id": 2,
    "task_id": 1,
    "title": "Run nmap",
    "description": "Full TCP port scan",
    "status": "finished",
    "result": "Open: 22,80,443",
    "context": "Linux host",
    "created_at": "2026-04-22T12:00:00Z",
    "updated_at": "2026-04-22T12:00:00Z",
}


# ---------------------------------------------------------------------------
# start_flow
# ---------------------------------------------------------------------------

@resp_mock.activate
def test_start_flow_success():
    resp_mock.add(resp_mock.POST, "https://pentagi.local/api/v1/flows/",
                  json=FLOW_DICT, status=200)
    flow = _client().start_flow("Scan 10.0.0.1", "openai")
    assert flow.id == 42
    assert flow.status == FlowStatus.created
    assert flow.provider == "openai"


@resp_mock.activate
def test_start_flow_sends_correct_body():
    resp_mock.add(resp_mock.POST, "https://pentagi.local/api/v1/flows/",
                  json=FLOW_DICT, status=200)
    _client().start_flow("My task", "anthropic")
    req_body = json.loads(resp_mock.calls[0].request.body)
    assert req_body["input"] == "My task"
    assert req_body["provider"] == "anthropic"


@resp_mock.activate
def test_start_flow_with_prompt_overrides():
    resp_mock.add(resp_mock.GET, "https://pentagi.local/api/v1/prompts/pentester",
                  json={"prompt": "original"}, status=200)
    resp_mock.add(resp_mock.PUT, "https://pentagi.local/api/v1/prompts/pentester",
                  json={}, status=200)
    resp_mock.add(resp_mock.POST, "https://pentagi.local/api/v1/flows/",
                  json=FLOW_DICT, status=200)

    flow = _client().start_flow(
        "task", "openai",
        prompt_overrides={"pentester": "Focus on web only"},
        restore_prompts=False,
    )
    assert flow.id == 42
    assert resp_mock.calls[1].request.method == "PUT"
    put_body = json.loads(resp_mock.calls[1].request.body)
    assert put_body["prompt"] == "Focus on web only"


@resp_mock.activate
def test_start_flow_401_raises_auth_error():
    resp_mock.add(resp_mock.POST, "https://pentagi.local/api/v1/flows/",
                  json={}, status=401)
    with pytest.raises(AuthError):
        _client().start_flow("task", "openai")


@resp_mock.activate
def test_start_flow_500_raises_api_error():
    resp_mock.add(resp_mock.POST, "https://pentagi.local/api/v1/flows/",
                  body="internal error", status=500)
    with pytest.raises(APIError) as exc_info:
        _client().start_flow("task", "openai")
    assert exc_info.value.status_code == 500


# ---------------------------------------------------------------------------
# reply_to_flow / stop_flow
# ---------------------------------------------------------------------------

@resp_mock.activate
def test_reply_to_flow_sends_correct_body():
    resp_mock.add(resp_mock.PUT, "https://pentagi.local/api/v1/flows/42",
                  json={}, status=200)
    _client().reply_to_flow(42, "proceed")
    body = json.loads(resp_mock.calls[0].request.body)
    assert body == {"action": "input", "input": "proceed"}


@resp_mock.activate
def test_stop_flow_sends_correct_body():
    resp_mock.add(resp_mock.PUT, "https://pentagi.local/api/v1/flows/42",
                  json={}, status=200)
    _client().stop_flow(42)
    body = json.loads(resp_mock.calls[0].request.body)
    assert body == {"action": "stop"}


@resp_mock.activate
def test_stop_flow_idempotent_on_4xx():
    resp_mock.add(resp_mock.PUT, "https://pentagi.local/api/v1/flows/42",
                  json={}, status=400)
    # Should not raise
    _client().stop_flow(42)


# ---------------------------------------------------------------------------
# get_tasks / get_subtasks / get_subtask
# ---------------------------------------------------------------------------

@resp_mock.activate
def test_get_tasks_returns_list():
    resp_mock.add(resp_mock.GET, "https://pentagi.local/api/v1/flows/42/tasks/",
                  json={"tasks": [TASK_DICT]}, status=200)
    tasks = _client().get_tasks(42)
    assert len(tasks) == 1
    assert tasks[0].id == 1
    assert tasks[0].status == FlowStatus.running


@resp_mock.activate
def test_get_subtasks_returns_list():
    resp_mock.add(resp_mock.GET, "https://pentagi.local/api/v1/flows/42/tasks/1/subtasks/",
                  json={"subtasks": [SUBTASK_DICT]}, status=200)
    subs = _client().get_subtasks(42, 1)
    assert len(subs) == 1
    assert subs[0].id == 2
    assert subs[0].status == FlowStatus.finished


@resp_mock.activate
def test_get_subtask_returns_detail():
    resp_mock.add(resp_mock.GET, "https://pentagi.local/api/v1/flows/42/tasks/1/subtasks/2",
                  json=SUBTASK_DICT, status=200)
    sub = _client().get_subtask(42, 1, 2)
    assert sub.description == "Full TCP port scan"
    assert sub.result == "Open: 22,80,443"
    assert sub.context == "Linux host"


@resp_mock.activate
def test_get_subtask_404_raises_api_error():
    resp_mock.add(resp_mock.GET, "https://pentagi.local/api/v1/flows/42/tasks/1/subtasks/99",
                  json={}, status=404)
    with pytest.raises(APIError) as exc_info:
        _client().get_subtask(42, 1, 99)
    assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# Streaming (mocked StreamingManager)
# ---------------------------------------------------------------------------

def _make_msg(msg_type: str, text: str) -> MessageLog:
    return MessageLog(
        id=1, flow_id=42, task_id=None, subtask_id=None,
        type=MessageType(msg_type), message=text,
        result=None, thinking=None,
        result_format=None,
        created_at=datetime.now(tz=timezone.utc),
    )


def test_messages_yields_from_stream():
    mock_msgs = [
        _make_msg("answer", "Scanning…"),
        _make_msg("report", "Port 80 open"),
        _make_msg("done", "Finished"),
    ]

    with patch("pentagi_client.client.StreamingManager") as MockManager:
        instance = MagicMock()
        instance.__iter__ = MagicMock(return_value=iter(mock_msgs))
        instance.__next__ = MagicMock(side_effect=mock_msgs + [StopIteration()])
        MockManager.return_value = instance

        result = list(_client().messages(42))
        assert len(result) == 3
        assert result[0].type == MessageType.answer
        assert result[2].type == MessageType.done


def test_messages_filters_by_type():
    mock_msgs = [
        _make_msg("answer", "text"),
        _make_msg("thoughts", "internal"),
        _make_msg("done", "end"),
    ]

    with patch("pentagi_client.client.StreamingManager") as MockManager:
        instance = MagicMock()
        instance.__iter__ = MagicMock(return_value=iter(mock_msgs))
        MockManager.return_value = instance

        result = list(_client().messages(42, types=["answer", "done"]))
        types_seen = [m.type.value for m in result]
        assert "thoughts" not in types_seen
        assert "answer" in types_seen
