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
        description=(
            "Tool call IDs from the current checkpointable observations manifest: "
            "successful inline tool results or raw artifact.read observations."
        ),
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
Use this tool to preserve model-organized task state. When a task plan is active,
it completes the current task item and advances the plan.

The checkpoint value is model-organized task state with references to its
supporting observations. A successful checkpoint means that this state was
accepted and the plan advanced; Runtime does not verify whether its conclusions
are correct or complete. Tool success means execution succeeded, not that its
business result was verified.

source_tool_call_ids must refer to current successful inline tool results or
raw artifact.read observations shown in the checkpoint manifest. Use candidate
IDs directly; do not repeat a query just to create an Artifact. Externalized
previews and wrappers, artifact.grep results, task-tool results, errors,
deferred results, and receipts are not checkpoint sources. Checkpointing does
not force externalization or release the source results from conversation
history. Final synthesis after all plan items are complete does not require
another checkpoint.
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
