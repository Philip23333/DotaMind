"""Model-facing task checkpoint tool."""

from __future__ import annotations

from typing import Any

from pydantic import Field

from app.vnext.agent.task_state import CheckpointSourceError, TaskStateCoordinator, TaskStateError
from app.vnext.domain.common.models import DomainModel
from app.vnext.tools.definition import ToolDefinition
from app.vnext.tools.errors import StructuredToolError
from app.vnext.tools.registry import ToolRegistry


class TaskCheckpointInput(DomainModel):
    key: str = Field(
        min_length=1,
        max_length=128,
        description=(
            "Must match the current item when a task plan is active. Without a plan, "
            "a new checkpoint under the same key replaces the whole earlier value."
        ),
    )
    value: dict[str, Any] = Field(
        min_length=1,
        description="Non-empty structured facts preserved for the task under this key.",
    )


class TaskCheckpointResult(DomainModel):
    checkpoint_id: str
    key: str
    source_count: int


TASK_CHECKPOINT_DESCRIPTION = """\
Use this tool to preserve model-organized task state. When a task plan is active,
it completes the current task item and advances the plan.

The checkpoint value is model-organized task state. Runtime automatically collects
eligible, unconsumed observations obtained while processing the current task in
this request. These are task activity records, not precise citations proving each
conclusion. A successful checkpoint means that this state was
accepted and the plan advanced; Runtime does not verify whether its conclusions
are correct or complete. Tool success means execution succeeded, not that its
business result was verified.

Submit only key and value; do not supply tool-call IDs. Successful ordinary results,
including unresolved outcomes and externalized results, and raw artifact.read
observations qualify. artifact.grep results, task-tool results, errors, deferred
results, and receipts do not. No eligible observations produces a recoverable
error without advancing the plan. Checkpointing does
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
            )
        except CheckpointSourceError as exc:
            raise StructuredToolError(
                "invalid_checkpoint_source",
                str(exc),
                exc.details,
            ) from exc
        except TaskStateError as exc:
            raise StructuredToolError("invalid_task_state", str(exc), exc.details) from exc
        return TaskCheckpointResult(
            checkpoint_id=result.checkpoint_id,
            key=result.key,
            source_count=len(result.source_tool_call_ids),
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
