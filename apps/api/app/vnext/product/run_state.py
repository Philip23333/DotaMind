"""Product-owned, request-local projection of one chat run's lifecycle."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated, Literal, TypeAlias
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator

RunStatus: TypeAlias = Literal["running", "completed", "failed", "cancelled"]
RunStage: TypeAlias = Literal["execution", "answer"]
AnswerKind: TypeAlias = Literal["primary", "degraded", "deterministic"]
AnswerStatus: TypeAlias = Literal["pending", "streaming", "ready", "interrupted"]
PersistenceStatus: TypeAlias = Literal["pending", "saving", "saved", "failed"]


class _ProductRunModel(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class ProductRunError(_ProductRunModel):
    scope: Literal["execution", "persistence"]
    code: str = Field(min_length=1)
    message: str = Field(min_length=1)


class ProductAnswerState(_ProductRunModel):
    attempt_id: str | None = Field(default=None, min_length=1)
    kind: AnswerKind | None = None
    text: str = ""
    status: AnswerStatus = "pending"


class ExecutionTiming(_ProductRunModel):
    started_at: AwareDatetime
    finished_at: AwareDatetime | None = None
    duration_seconds: float | None = Field(default=None, ge=0)

    @field_validator("started_at", "finished_at")
    @classmethod
    def _store_utc(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("execution timing timestamps must include a timezone")
        return value.astimezone(timezone.utc)

    @model_validator(mode="after")
    def _finished_values_are_paired(self) -> ExecutionTiming:
        if (self.finished_at is None) != (self.duration_seconds is None):
            raise ValueError("finished_at and duration_seconds must be set together")
        return self


class StageActivity(_ProductRunModel):
    kind: Literal["stage"] = "stage"
    id: str = Field(min_length=1)
    stage: RunStage


class ToolActivity(_ProductRunModel):
    kind: Literal["tool"] = "tool"
    id: str = Field(min_length=1)
    tool_name: str = Field(min_length=1)
    status: Literal["running", "completed", "failed"] = "running"
    duration_seconds: float | None = Field(default=None, ge=0)
    error_code: str | None = Field(default=None, min_length=1)


class CommentaryActivity(_ProductRunModel):
    kind: Literal["commentary"] = "commentary"
    id: str = Field(min_length=1)
    text: str
    truncated: bool = False


ActivityItem: TypeAlias = Annotated[
    StageActivity | ToolActivity | CommentaryActivity,
    Field(discriminator="kind"),
]


class ProductRunState(_ProductRunModel):
    request_id: UUID
    assistant_message_id: str = Field(min_length=1)
    status: RunStatus = "running"
    stage: RunStage = "execution"
    activity: list[ActivityItem] = Field(default_factory=list)
    omitted_activity_count: int = Field(default=0, ge=0)
    execution_timing: ExecutionTiming | None = None
    answer: ProductAnswerState = Field(default_factory=ProductAnswerState)
    persistence: PersistenceStatus = "pending"
    error: ProductRunError | None = None


class ProductRunStateProjector:
    """Synchronously project lifecycle facts into a bounded product Run State."""

    MAX_ACTIVITY_ITEMS = 100
    MAX_COMMENTARY_CODE_POINTS = 2_000

    def __init__(self, request_id: UUID, assistant_message_id: str) -> None:
        self._state = ProductRunState(
            request_id=request_id,
            assistant_message_id=assistant_message_id,
        )
        self._append_activity(StageActivity(id="stage:execution", stage="execution"))

    @classmethod
    def from_completed_answer(
        cls,
        request_id: UUID,
        assistant_message_id: str,
        text: str,
        *,
        attempt_id: str | None = None,
        kind: AnswerKind | None = None,
    ) -> ProductRunStateProjector:
        """Restore a server-owned canonical answer without inventing Runtime activity."""

        if (attempt_id is None) != (kind is None):
            raise ValueError("attempt_id and kind must either both be present or both be absent")
        projector = cls.__new__(cls)
        projector._state = ProductRunState(
            request_id=request_id,
            assistant_message_id=assistant_message_id,
            status="completed",
            stage="answer",
            activity=[],
            answer=ProductAnswerState(
                attempt_id=attempt_id,
                kind=kind,
                text=text,
                status="ready",
            ),
            persistence="pending",
        )
        return projector

    def snapshot(self) -> ProductRunState:
        """Return a deep copy so consumers cannot mutate projection state."""

        return self._state.model_copy(deep=True)

    def start_execution(self, started_at: datetime) -> None:
        if self._state.status != "running" or self._state.execution_timing is not None:
            return
        self._state.execution_timing = ExecutionTiming(started_at=started_at)

    def add_commentary(self, step: int, text: str) -> None:
        if (
            self._state.status != "running"
            or self._state.stage != "execution"
            or not text.strip()
        ):
            return

        activity_id = f"commentary:{step}"
        if any(
            isinstance(item, CommentaryActivity) and item.id == activity_id
            for item in self._state.activity
        ):
            return

        display_text = text[: self.MAX_COMMENTARY_CODE_POINTS]
        self._append_activity(
            CommentaryActivity(
                id=activity_id,
                text=display_text,
                truncated=len(text) > self.MAX_COMMENTARY_CODE_POINTS,
            )
        )

    def enter_stage(self, stage: RunStage, *, timestamp: datetime | None = None) -> None:
        if self._state.status != "running":
            return
        if stage not in ("execution", "answer"):
            raise ValueError("stage must be execution or answer")
        if stage == self._state.stage:
            return
        if self._state.stage == "answer":
            raise ValueError("cannot return to the execution stage")

        self._finish_execution(timestamp)
        self._state.stage = "answer"
        self._append_activity(StageActivity(id="stage:answer", stage="answer"))

    def tool_started(self, tool_call_id: str, tool_name: str) -> None:
        if self._state.status != "running" or self._state.stage != "execution":
            return

        activity = ToolActivity(id=tool_call_id, tool_name=tool_name)
        if any(
            isinstance(item, ToolActivity) and item.id == tool_call_id
            for item in self._state.activity
        ):
            return
        self._append_activity(activity)

    def tool_finished(
        self,
        tool_call_id: str,
        *,
        duration_seconds: float | None,
        error_code: str | None = None,
    ) -> None:
        if duration_seconds is not None and duration_seconds < 0:
            raise ValueError("duration_seconds must be non-negative")
        if self._state.status != "running":
            return

        for index, item in enumerate(self._state.activity):
            if not isinstance(item, ToolActivity) or item.id != tool_call_id:
                continue
            if item.status != "running":
                return
            status: Literal["completed", "failed"] = (
                "failed" if error_code is not None else "completed"
            )
            self._state.activity[index] = ToolActivity(
                id=item.id,
                tool_name=item.tool_name,
                status=status,
                duration_seconds=duration_seconds,
                error_code=error_code,
            )
            return

    def start_answer_attempt(self, attempt_id: str, kind: AnswerKind) -> None:
        if self._state.status != "running" or self._state.stage != "answer":
            raise ValueError("answer attempts require a running answer stage")

        next_answer = ProductAnswerState(attempt_id=attempt_id, kind=kind)
        if self._state.answer.attempt_id == attempt_id:
            if self._state.answer.kind == kind:
                return
            raise ValueError("an attempt ID cannot change answer kind")

        self._state.answer = next_answer

    def append_answer_text(self, attempt_id: str, text: str) -> None:
        if not text:
            return
        if (
            self._state.status != "running"
            or self._state.answer.attempt_id != attempt_id
        ):
            return

        self._state.answer.text += text
        self._state.answer.status = "streaming"

    def complete_answer(self, attempt_id: str, text: str) -> None:
        if (
            self._state.status != "running"
            or self._state.answer.attempt_id != attempt_id
        ):
            return

        self._state.answer.text = text
        self._state.answer.status = "ready"
        self._state.status = "completed"
        if self._state.error is not None and self._state.error.scope == "execution":
            self._state.error = None

    def cancel(self, *, timestamp: datetime | None = None) -> None:
        if self._state.status != "running":
            return

        self._finish_execution(timestamp)
        self._state.status = "cancelled"
        if self._state.answer.text:
            self._state.answer.status = "interrupted"

    def fail_execution(
        self,
        code: str,
        message: str,
        *,
        timestamp: datetime | None = None,
    ) -> None:
        if self._state.status != "running":
            return

        self._finish_execution(timestamp)
        error = ProductRunError(scope="execution", code=code, message=message)
        self._state.status = "failed"
        self._state.error = error
        if self._state.answer.text:
            self._state.answer.status = "interrupted"

    def start_persistence(self) -> None:
        if self._state.status != "completed" or self._state.answer.status != "ready":
            raise ValueError("persistence requires a completed, ready answer")
        if self._state.persistence in ("saving", "saved"):
            return

        self._state.persistence = "saving"
        if self._state.error is not None and self._state.error.scope == "persistence":
            self._state.error = None

    def persistence_succeeded(self) -> None:
        if self._state.persistence == "saved":
            return
        if self._state.persistence != "saving":
            raise ValueError("persistence success requires a saving state")

        self._state.persistence = "saved"
        if self._state.error is not None and self._state.error.scope == "persistence":
            self._state.error = None

    def persistence_failed(self, code: str, message: str) -> None:
        if self._state.persistence != "saving":
            raise ValueError("persistence failure requires a saving state")

        error = ProductRunError(scope="persistence", code=code, message=message)
        self._state.persistence = "failed"
        self._state.error = error

    def _append_activity(self, item: ActivityItem) -> None:
        self._state.activity.append(item)
        excess = len(self._state.activity) - self.MAX_ACTIVITY_ITEMS
        if excess > 0:
            del self._state.activity[:excess]
            self._state.omitted_activity_count += excess

    def _finish_execution(self, timestamp: datetime | None) -> None:
        timing = self._state.execution_timing
        if timing is None or timing.finished_at is not None:
            return

        finished_at = _as_utc(timestamp or datetime.now(timezone.utc))
        self._state.execution_timing = ExecutionTiming(
            started_at=timing.started_at,
            finished_at=finished_at,
            duration_seconds=max(
                0.0,
                (finished_at - timing.started_at).total_seconds(),
            ),
        )


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("execution timing timestamps must include a timezone")
    return value.astimezone(timezone.utc)


__all__ = [
    "ActivityItem",
    "CommentaryActivity",
    "ExecutionTiming",
    "ProductAnswerState",
    "ProductRunError",
    "ProductRunState",
    "ProductRunStateProjector",
    "StageActivity",
    "ToolActivity",
]
