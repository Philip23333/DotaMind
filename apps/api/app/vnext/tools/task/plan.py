"""Model-facing serial task-plan tool."""

from __future__ import annotations

from pydantic import Field

from app.vnext.agent.task_state import TaskStateCoordinator
from app.vnext.domain.common.models import DomainModel
from app.vnext.tools.definition import ToolDefinition
from app.vnext.tools.registry import ToolRegistry


class TaskPlanItemInput(DomainModel):
    key: str = Field(
        min_length=1,
        max_length=128,
        description="Stable key for one independently completable task result unit.",
    )
    objective: str = Field(
        min_length=1,
        max_length=512,
        description="Concrete objective whose structured result can be checkpointed.",
    )


class TaskPlanInput(DomainModel):
    items: list[TaskPlanItemInput] = Field(
        min_length=2,
        max_length=16,
        description="Serial task items; the first item becomes active immediately.",
    )


class TaskPlanResult(DomainModel):
    item_count: int
    current_key: str | None


TASK_PLAN_DESCRIPTION = """\
Create a serial plan for a complex artifact-backed task. Each item is an
independently completable result unit; complete the current item before moving
to a later item. Use task.checkpoint to preserve the current item's result.
"""


def register_task_plan_tool(
    registry: ToolRegistry,
    coordinator: TaskStateCoordinator,
) -> None:
    async def plan(args: TaskPlanInput) -> TaskPlanResult:
        created = coordinator.create_plan(
            [item.model_dump(mode="python") for item in args.items]
        )
        return TaskPlanResult(
            item_count=len(created.items),
            current_key=created.current_key,
        )

    registry.register(
        ToolDefinition(
            name="task.plan",
            description=TASK_PLAN_DESCRIPTION,
            input_model=TaskPlanInput,
            output_model=TaskPlanResult,
            handler=plan,
            read_only=False,
            parallel_safe=False,
            externalize_result=False,
        )
    )


__all__ = [
    "TASK_PLAN_DESCRIPTION",
    "TaskPlanInput",
    "TaskPlanItemInput",
    "TaskPlanResult",
    "register_task_plan_tool",
]
