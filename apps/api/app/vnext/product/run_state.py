"""Product-owned, request-local projection of one chat run's lifecycle."""

from __future__ import annotations

from typing import Annotated, Literal, TypeAlias
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

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


ActivityItem: TypeAlias = Annotated[
    StageActivity | ToolActivity,
    Field(discriminator="kind"),
]


class ProductRunState(_ProductRunModel):
    request_id: UUID
    assistant_message_id: str = Field(min_length=1)
    status: RunStatus = "running"
    stage: RunStage = "execution"
    activity: list[ActivityItem] = Field(default_factory=list)
    omitted_activity_count: int = Field(default=0, ge=0)
    answer: ProductAnswerState = Field(default_factory=ProductAnswerState)
    persistence: PersistenceStatus = "pending"
    error: ProductRunError | None = None


class ProductRunStateProjector:
    """Synchronously project lifecycle facts into a bounded product Run State."""

    MAX_ACTIVITY_ITEMS = 100

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

    def enter_stage(self, stage: RunStage) -> None:
        if self._state.status != "running":
            return
        if stage not in ("execution", "answer"):
            raise ValueError("stage must be execution or answer")
        if stage == self._state.stage:
            return
        if self._state.stage == "answer":
            raise ValueError("cannot return to the execution stage")

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

    def cancel(self) -> None:
        if self._state.status != "running":
            return

        self._state.status = "cancelled"
        if self._state.answer.text:
            self._state.answer.status = "interrupted"

    def fail_execution(self, code: str, message: str) -> None:
        if self._state.status != "running":
            return

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


__all__ = [
    "ActivityItem",
    "ProductAnswerState",
    "ProductRunError",
    "ProductRunState",
    "ProductRunStateProjector",
    "StageActivity",
    "ToolActivity",
]
