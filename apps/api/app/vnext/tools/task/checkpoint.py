"""Model-facing task checkpoint tool."""

from __future__ import annotations

from typing import Any

from pydantic import Field, field_validator

from app.vnext.agent.task_state import CheckpointSourceError, TaskStateCoordinator
from app.vnext.domain.common.models import DomainModel
from app.vnext.tools.definition import ToolDefinition
from app.vnext.tools.errors import StructuredToolError
from app.vnext.tools.registry import ToolRegistry


class TaskCheckpointInput(DomainModel):
    key: str = Field(
        min_length=1,
        max_length=128,
        description="Stable task-state key whose latest checkpoint replaces earlier values.",
    )
    value: dict[str, Any] = Field(
        min_length=1,
        description="Non-empty structured facts preserved for the task under this key.",
    )
    source_tool_call_ids: list[str] = Field(
        min_length=1,
        description="Tool call IDs from the current checkpointable artifact observation manifest.",
    )

    @field_validator("source_tool_call_ids")
    @classmethod
    def _validate_source_ids(cls, value: list[str]) -> list[str]:
        if any(not source for source in value):
            raise ValueError("source tool call IDs must not be empty")
        return value


class TaskCheckpointResult(DomainModel):
    checkpoint_id: str
    key: str
    accepted_source_tool_call_ids: list[str]


TASK_CHECKPOINT_DESCRIPTION = """\
When a task plan is active, use this tool to complete the current task item.

The checkpoint value must preserve all information from the referenced raw
observations that may still be needed for the user's final answer. A successful
checkpoint completes the current task item and advances the plan to the next
item. The value is the structured task state to retain, and
source_tool_call_ids must refer to current successful raw artifact.read
observations shown in the checkpoint manifest. Final synthesis after all plan
items are complete does not require another checkpoint.
"""


def register_task_checkpoint_tool(
    registry: ToolRegistry,
    coordinator: TaskStateCoordinator,
) -> None:
    async def checkpoint(args: TaskCheckpointInput) -> TaskCheckpointResult:
        try:
            result = coordinator.create_checkpoint(
                args.key,
                args.value,
                args.source_tool_call_ids,
            )
        except CheckpointSourceError as exc:
            raise StructuredToolError(
                "invalid_checkpoint_source",
                str(exc),
                exc.details,
            ) from exc
        return TaskCheckpointResult(
            checkpoint_id=result.checkpoint_id,
            key=result.key,
            accepted_source_tool_call_ids=list(result.source_tool_call_ids),
        )

    registry.register(
        ToolDefinition(
            name="task.checkpoint",
            description=TASK_CHECKPOINT_DESCRIPTION,
            input_model=TaskCheckpointInput,
            output_model=TaskCheckpointResult,
            handler=checkpoint,
            read_only=False,
            parallel_safe=False,
            externalize_result=False,
        )
    )


__all__ = [
    "TASK_CHECKPOINT_DESCRIPTION",
    "TaskCheckpointInput",
    "TaskCheckpointResult",
    "register_task_checkpoint_tool",
]
