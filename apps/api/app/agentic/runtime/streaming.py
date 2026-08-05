"""Request-scoped safe runtime events for the public plan stream."""

from collections.abc import Callable
from contextvars import ContextVar, Token
from typing import Any, Literal, TypeAlias

from pydantic import BaseModel, ConfigDict


class _StreamEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PhaseStreamEvent(_StreamEvent):
    type: Literal["phase"] = "phase"
    phase: Literal["planning", "tool_execution", "answering", "reviewing"]
    attempt_index: int


class ToolStreamEvent(_StreamEvent):
    type: Literal["tool"] = "tool"
    tool_call_id: str
    tool: str
    attempt_index: int
    status: Literal["running", "ok", "error"]
    latency_ms: int | None = None
    reused: bool | None = None
    failure_code: str | None = None


class AnswerDeltaStreamEvent(_StreamEvent):
    type: Literal["answer_delta"] = "answer_delta"
    delta: str
    attempt_index: int
    provisional: Literal[True] = True


class ResultStreamEvent(_StreamEvent):
    type: Literal["result"] = "result"
    response: dict[str, Any]
    session: dict[str, Any] | None = None


class ErrorStreamEvent(_StreamEvent):
    type: Literal["error"] = "error"
    error_code: str
    reason: str


PlanStreamEvent: TypeAlias = (
    PhaseStreamEvent
    | ToolStreamEvent
    | AnswerDeltaStreamEvent
    | ResultStreamEvent
    | ErrorStreamEvent
)
StreamEventPublisher: TypeAlias = Callable[[PlanStreamEvent], None]

_publisher: ContextVar[StreamEventPublisher | None] = ContextVar(
    "plan_stream_event_publisher", default=None
)


def bind_stream_event_publisher(
    publisher: StreamEventPublisher,
) -> Token[StreamEventPublisher | None]:
    """Bind a publisher before creating the request execution task."""

    return _publisher.set(publisher)


def reset_stream_event_publisher(token: Token[StreamEventPublisher | None]) -> None:
    _publisher.reset(token)


def publish_stream_event(event: PlanStreamEvent) -> None:
    """Publish only when the current request is serving a stream."""

    publisher = _publisher.get()
    if publisher is not None:
        publisher(event)


def stream_events_enabled() -> bool:
    return _publisher.get() is not None
