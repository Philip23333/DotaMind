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
    handler_entered: bool | None = None
    dispatch_stage: str | None = None


class ObserverStreamEvent(_StreamEvent):
    """Test-only full-fidelity model/tool observation carried by the Run stream."""

    type: Literal["observer"] = "observer"
    kind: Literal["model_prompt", "model_output", "tool_input", "tool_output"]
    stage: Literal["controller", "answer", "tool"]
    call_id: str
    name: str
    attempt_index: int
    payload: dict[str, Any]


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


class StatusStreamEvent(_StreamEvent):
    type: Literal["status"] = "status"
    status: Literal[
        "queued",
        "running",
        "cancel_requested",
        "completed",
        "failed",
        "cancelled",
        "interrupted",
    ]
    error_code: str | None = None
    transcript_recovery: bool = False


PlanStreamEvent: TypeAlias = (
    PhaseStreamEvent
    | ToolStreamEvent
    | ObserverStreamEvent
    | AnswerDeltaStreamEvent
    | ResultStreamEvent
    | ErrorStreamEvent
    | StatusStreamEvent
)
StreamEventPublisher: TypeAlias = Callable[[PlanStreamEvent], None]

_publisher: ContextVar[StreamEventPublisher | None] = ContextVar(
    "plan_stream_event_publisher", default=None
)
_observer_attempt_index: ContextVar[int] = ContextVar(
    "observer_attempt_index", default=0
)


def bind_stream_event_publisher(
    publisher: StreamEventPublisher,
) -> Token[StreamEventPublisher | None]:
    """Bind a publisher before creating the request execution task."""

    return _publisher.set(publisher)


def reset_stream_event_publisher(token: Token[StreamEventPublisher | None]) -> None:
    _publisher.reset(token)


def bind_observer_attempt_index(attempt_index: int) -> Token[int]:
    return _observer_attempt_index.set(attempt_index)


def reset_observer_attempt_index(token: Token[int]) -> None:
    _observer_attempt_index.reset(token)


def current_observer_attempt_index() -> int:
    return _observer_attempt_index.get()


def publish_stream_event(event: PlanStreamEvent) -> None:
    """Publish only when the current request is serving a stream."""

    publisher = _publisher.get()
    if publisher is not None:
        publisher(event)


def stream_events_enabled() -> bool:
    return _publisher.get() is not None


def observer_events_enabled() -> bool:
    """Return true only for an active stream with the explicit test flag enabled."""

    if not stream_events_enabled():
        return False
    from app.core.config import get_settings

    return get_settings().test_observer_enabled


def publish_observer_event(event: ObserverStreamEvent) -> None:
    if observer_events_enabled():
        publish_stream_event(event)
