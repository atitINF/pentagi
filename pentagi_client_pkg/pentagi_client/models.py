from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import List, Optional


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

class FlowStatus(str, Enum):
    created = "created"
    running = "running"
    waiting = "waiting"
    finished = "finished"
    failed = "failed"


class MessageType(str, Enum):
    answer = "answer"
    report = "report"
    thoughts = "thoughts"
    browser = "browser"
    terminal = "terminal"
    file = "file"
    search = "search"
    advice = "advice"
    ask = "ask"
    input = "input"
    done = "done"
    reconnect = "reconnect"  # synthetic, client-generated


class ResultFormat(str, Enum):
    plain = "plain"
    markdown = "markdown"
    terminal = "terminal"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_dt(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return dt
    except (ValueError, AttributeError):
        return None


def _require_dt(value: Optional[str], field_name: str) -> datetime:
    dt = _parse_dt(value)
    if dt is None:
        return datetime.now(tz=timezone.utc)
    return dt


def _flow_status(value: str) -> FlowStatus:
    try:
        return FlowStatus(value)
    except ValueError:
        return FlowStatus.running


def _message_type(value: str) -> MessageType:
    try:
        return MessageType(value)
    except ValueError:
        return MessageType.answer


def _result_format(value: str) -> ResultFormat:
    try:
        return ResultFormat(value)
    except ValueError:
        return ResultFormat.plain


# ---------------------------------------------------------------------------
# Entities
# ---------------------------------------------------------------------------

@dataclass
class Flow:
    id: int
    title: str
    status: FlowStatus
    provider: str
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_dict(cls, d: dict) -> "Flow":
        provider = ""
        if isinstance(d.get("model_provider_type"), str):
            provider = d["model_provider_type"]
        elif isinstance(d.get("provider"), dict):
            provider = d["provider"].get("type", "")
        elif isinstance(d.get("provider"), str):
            provider = d["provider"]

        return cls(
            id=int(d["id"]),
            title=d.get("title", ""),
            status=_flow_status(d.get("status", "created")),
            provider=provider,
            created_at=_require_dt(d.get("created_at"), "created_at"),
            updated_at=_require_dt(d.get("updated_at"), "updated_at"),
        )


@dataclass
class Subtask:
    id: int
    task_id: int
    title: str
    description: str
    status: FlowStatus
    result: Optional[str]
    context: Optional[str]
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_dict(cls, d: dict) -> "Subtask":
        return cls(
            id=int(d["id"]),
            task_id=int(d["task_id"]),
            title=d.get("title", ""),
            description=d.get("description", ""),
            status=_flow_status(d.get("status", "created")),
            result=d.get("result") or None,
            context=d.get("context") or None,
            created_at=_require_dt(d.get("created_at"), "created_at"),
            updated_at=_require_dt(d.get("updated_at"), "updated_at"),
        )


@dataclass
class Task:
    id: int
    flow_id: int
    title: str
    status: FlowStatus
    input: str
    result: Optional[str]
    subtasks: List[Subtask] = field(default_factory=list)
    created_at: datetime = field(default_factory=lambda: datetime.now(tz=timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(tz=timezone.utc))

    @classmethod
    def from_dict(cls, d: dict) -> "Task":
        subtasks = [Subtask.from_dict(s) for s in d.get("subtasks") or []]
        return cls(
            id=int(d["id"]),
            flow_id=int(d["flow_id"]),
            title=d.get("title", ""),
            status=_flow_status(d.get("status", "created")),
            input=d.get("input", ""),
            result=d.get("result") or None,
            subtasks=subtasks,
            created_at=_require_dt(d.get("created_at"), "created_at"),
            updated_at=_require_dt(d.get("updated_at"), "updated_at"),
        )


@dataclass
class Assistant:
    id: int
    flow_id: int
    title: str
    status: FlowStatus
    provider: str
    use_agents: bool
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_dict(cls, d: dict) -> "Assistant":
        provider = ""
        if isinstance(d.get("provider"), dict):
            provider = d["provider"].get("type", "")
        elif isinstance(d.get("model_provider_type"), str):
            provider = d["model_provider_type"]
        return cls(
            id=int(d["id"]),
            flow_id=int(d["flow_id"]),
            title=d.get("title", ""),
            status=_flow_status(d.get("status", "created")),
            provider=provider,
            use_agents=bool(d.get("use_agents", False)),
            created_at=_require_dt(d.get("created_at"), "created_at"),
            updated_at=_require_dt(d.get("updated_at"), "updated_at"),
        )


@dataclass
class AssistantLog:
    id: Optional[int]
    flow_id: Optional[int]
    assistant_id: Optional[int]
    type: MessageType
    message: str
    result: Optional[str]
    thinking: Optional[str]
    result_format: ResultFormat
    append_part: bool
    created_at: Optional[datetime]

    @classmethod
    def from_dict(cls, d: dict) -> "AssistantLog":
        return cls(
            id=int(d["id"]) if d.get("id") is not None else None,
            flow_id=int(d["flowId"]) if d.get("flowId") is not None else None,
            assistant_id=int(d["assistantId"]) if d.get("assistantId") is not None else None,
            type=_message_type(d.get("type", "answer")),
            message=d.get("message", ""),
            result=d.get("result") or None,
            thinking=d.get("thinking") or None,
            result_format=_result_format(d.get("resultFormat") or d.get("result_format", "plain")),
            append_part=bool(d.get("appendPart", False)),
            created_at=_parse_dt(d.get("createdAt") or d.get("created_at")),
        )

    @classmethod
    def synthetic(cls, msg_type: MessageType, message: str) -> "AssistantLog":
        return cls(
            id=None, flow_id=None, assistant_id=None,
            type=msg_type, message=message, result=None, thinking=None,
            result_format=ResultFormat.plain, append_part=False,
            created_at=datetime.now(tz=timezone.utc),
        )


@dataclass
class MessageLog:
    id: Optional[int]
    flow_id: Optional[int]
    task_id: Optional[int]
    subtask_id: Optional[int]
    type: MessageType
    message: str
    result: Optional[str]
    thinking: Optional[str]
    result_format: ResultFormat
    created_at: Optional[datetime]

    @classmethod
    def from_dict(cls, d: dict) -> "MessageLog":
        raw_flow = d.get("flow_id") or d.get("flowId")
        raw_task = d.get("task_id") or d.get("taskId")
        raw_sub  = d.get("subtask_id") or d.get("subtaskId")
        return cls(
            id=int(d["id"]) if d.get("id") is not None else None,
            flow_id=int(raw_flow) if raw_flow is not None else None,
            task_id=int(raw_task) if raw_task is not None else None,
            subtask_id=int(raw_sub) if raw_sub is not None else None,
            type=_message_type(d.get("type", "answer")),
            message=d.get("message", ""),
            result=d.get("result") or None,
            thinking=d.get("thinking") or None,
            result_format=_result_format(d.get("result_format") or d.get("resultFormat", "plain")),
            created_at=_parse_dt(d.get("created_at") or d.get("createdAt")),
        )

    @classmethod
    def synthetic(cls, msg_type: MessageType, message: str) -> "MessageLog":
        return cls(
            id=None,
            flow_id=None,
            task_id=None,
            subtask_id=None,
            type=msg_type,
            message=message,
            result=None,
            thinking=None,
            result_format=ResultFormat.plain,
            created_at=datetime.now(tz=timezone.utc),
        )
