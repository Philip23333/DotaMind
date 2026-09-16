"""Ephemeral task checkpoints and active artifact observation context."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from typing import Any
from uuid import uuid4

from app.vnext.artifacts.lifecycle import (
    ArtifactObservation,
    collect_active_artifact_observations,
)
from app.vnext.llm.protocol import Message


@dataclass(frozen=True, slots=True)
class TaskCheckpoint:
    """The latest checkpoint value for one model-chosen task key."""

    checkpoint_id: str
    key: str
    value: dict[str, Any]
    source_tool_call_ids: tuple[str, ...]


class TaskItemStatus(str, Enum):
    """Lifecycle status for one serial task-plan item."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"


@dataclass(frozen=True, slots=True)
class TaskItem:
    """One independently completable unit in a task plan."""

    key: str
    objective: str
    status: TaskItemStatus


@dataclass(frozen=True, slots=True)
class TaskPlan:
    """Immutable snapshot of the active serial task plan."""

    items: tuple[TaskItem, ...]
    current_key: str | None


class TaskStateStore:
    """In-memory latest-value storage for one runtime invocation."""

    def __init__(self) -> None:
        self._checkpoints: dict[str, TaskCheckpoint] = {}

    def put(self, checkpoint: TaskCheckpoint) -> None:
        self._checkpoints[checkpoint.key] = checkpoint

    def get(self, key: str) -> TaskCheckpoint | None:
        return self._checkpoints.get(key)

    def list(self) -> list[TaskCheckpoint]:
        return [self._checkpoints[key] for key in sorted(self._checkpoints)]

    def snapshot(self) -> dict[str, TaskCheckpoint]:
        return {key: self._checkpoints[key] for key in sorted(self._checkpoints)}


class TaskStateCoordinator:
    """Coordinate ephemeral checkpoint state with the current raw observations."""

    def __init__(self, store: TaskStateStore | None = None) -> None:
        self.store = store or TaskStateStore()
        self.plan: TaskPlan | None = None
        self._active_observations: dict[str, ArtifactObservation] = {}
        self._claimed_source_tool_call_ids: set[str] = set()

    def refresh(self, messages: Sequence[Message]) -> None:
        observations = collect_active_artifact_observations(messages)
        self._active_observations = {
            observation.tool_call_id: observation for observation in observations
            if observation.tool_call_id not in self._claimed_source_tool_call_ids
            }

    def create_plan(self, items: Sequence[Mapping[str, Any]]) -> TaskPlan:
        """Create the one serial plan allowed for this runtime invocation."""

        if self.plan is not None:
            raise ValueError("task plan already exists")
        if not 2 <= len(items) <= 16:
            raise ValueError("task plan must contain between 2 and 16 items")

        validated: list[TaskItem] = []
        seen_keys: set[str] = set()
        for item in items:
            if not isinstance(item, Mapping):
                raise ValueError("task plan items must be dictionaries")
            key = item.get("key")
            objective = item.get("objective")
            if not isinstance(key, str) or not key or len(key) > 128:
                raise ValueError(
                    "task plan item key must be a non-empty string of at most 128 characters"
                )
            if key in seen_keys:
                raise ValueError("task plan item keys must be unique")
            if not isinstance(objective, str) or not objective or len(objective) > 512:
                raise ValueError(
                    "task plan item objective must be a non-empty string of at most 512 characters"
                )
            seen_keys.add(key)
            validated.append(
                TaskItem(
                    key=key,
                    objective=objective,
                    status=(
                        TaskItemStatus.IN_PROGRESS
                        if not validated
                        else TaskItemStatus.PENDING
                    ),
                )
            )

        plan = TaskPlan(items=tuple(validated), current_key=validated[0].key)
        self.plan = plan
        return plan

    def current_item(self) -> TaskItem | None:
        """Return the current item in the active plan, if any."""

        if self.plan is None or self.plan.current_key is None:
            return None
        return next(
            (item for item in self.plan.items if item.key == self.plan.current_key),
            None,
        )

    def plan_snapshot(self) -> TaskPlan | None:
        """Return the immutable active-plan snapshot."""

        return self.plan

    def create_checkpoint(
        self,
        key: str,
        value: dict[str, Any],
        source_tool_call_ids: Sequence[str],
    ) -> TaskCheckpoint:
        sources = tuple(source_tool_call_ids)
        self._validate_checkpoint(key, value, sources)
        next_plan = _advance_plan(self.plan) if self.plan is not None else None
        checkpoint = TaskCheckpoint(
            checkpoint_id=f"checkpoint:{uuid4()}",
            key=key,
            value=dict(value),
            source_tool_call_ids=sources,
        )
        self.store.put(checkpoint)
        self._claimed_source_tool_call_ids.update(sources)
        for source in sources:
            self._active_observations.pop(source, None)
        if next_plan is not None:
            self.plan = next_plan
        return checkpoint

    def render_context(self) -> str | None:
        payload = self.context_payload()
        if (
            payload["task_plan"] is None
            and not payload["task_state"]
            and not payload["active_manifest"]
        ):
            return None

        sections: list[str] = []
        task_plan = payload["task_plan"]
        if task_plan is not None:
            current = task_plan["current_key"] or "None"
            lines = [f"Task plan:\ncurrent: {current}"]
            lines.extend(
                f"- {item['key']} [{item['status']}] {item['objective']}"
                for item in task_plan["items"]
            )
            sections.append("\n".join(lines))
        sections.append("Task state:\n" + _json(payload["task_state"]))
        sections.append(
            "Checkpointable artifact observations:\n"
            + _json(payload["active_manifest"])
        )
        return "\n\n".join(sections)

    def context_payload(self) -> dict[str, Any]:
        """Return the structured ephemeral payload used by model context."""

        checkpoints = self.store.list()
        observations = list(self._active_observations.values())
        return {
            "task_plan": _plan_payload(self.plan),
            "task_state": {
                checkpoint.key: dict(checkpoint.value) for checkpoint in checkpoints
            },
            "active_manifest": [_manifest_item(observation) for observation in observations],
        }

    def _validate_checkpoint(
        self,
        key: str,
        value: dict[str, Any],
        source_tool_call_ids: tuple[str, ...],
    ) -> None:
        if not isinstance(key, str) or not key or len(key) > 128:
            raise ValueError("checkpoint key must be a non-empty string of at most 128 characters")
        if not isinstance(value, dict) or not value or not all(
            isinstance(item_key, str) for item_key in value
        ):
            raise ValueError("checkpoint value must be a non-empty dictionary")
        if not source_tool_call_ids:
            raise ValueError("checkpoint sources must not be empty")
        if any(
            not isinstance(tool_call_id, str) or not tool_call_id
            for tool_call_id in source_tool_call_ids
        ):
            raise ValueError("checkpoint sources must contain non-empty tool call IDs")
        if len(set(source_tool_call_ids)) != len(source_tool_call_ids):
            raise ValueError("checkpoint sources must not contain duplicates")
        if self.plan is not None:
            if self.plan.current_key is None:
                raise ValueError("task plan is already complete")
            if key != self.plan.current_key:
                raise ValueError(
                    "checkpoint key must match current task plan item: "
                    + self.plan.current_key
                )
        claimed = [
            tool_call_id
            for tool_call_id in source_tool_call_ids
            if tool_call_id in self._claimed_source_tool_call_ids
        ]
        if claimed:
            raise ValueError(
                "checkpoint sources have already been claimed: "
                + ", ".join(claimed)
            )
        unknown = [
            tool_call_id
            for tool_call_id in source_tool_call_ids
            if tool_call_id not in self._active_observations
        ]
        if unknown:
            raise ValueError(
                "checkpoint sources must refer to active raw artifact.read observations: "
                + ", ".join(unknown)
            )


def _manifest_item(observation: ArtifactObservation) -> dict[str, Any]:
    item: dict[str, Any] = {
        "tool_call_id": observation.tool_call_id,
        "ref": observation.ref,
        "path": observation.path,
    }
    if observation.actual_start is not None:
        item["actual_start"] = observation.actual_start
    if observation.actual_end is not None:
        item["actual_end"] = observation.actual_end
    return item


def _plan_payload(plan: TaskPlan | None) -> dict[str, Any] | None:
    if plan is None:
        return None
    return {
        "current_key": plan.current_key,
        "items": [
            {
                "key": item.key,
                "objective": item.objective,
                "status": item.status.value,
            }
            for item in plan.items
        ],
    }


def _advance_plan(plan: TaskPlan) -> TaskPlan:
    if plan.current_key is None:
        raise ValueError("task plan is already complete")
    current_index = next(
        (index for index, item in enumerate(plan.items) if item.key == plan.current_key),
        None,
    )
    if current_index is None:
        raise ValueError("task plan current item is invalid")
    items = list(plan.items)
    items[current_index] = TaskItem(
        key=items[current_index].key,
        objective=items[current_index].objective,
        status=TaskItemStatus.COMPLETED,
    )
    next_index = current_index + 1
    if next_index >= len(items):
        return TaskPlan(items=tuple(items), current_key=None)
    items[next_index] = TaskItem(
        key=items[next_index].key,
        objective=items[next_index].objective,
        status=TaskItemStatus.IN_PROGRESS,
    )
    return TaskPlan(items=tuple(items), current_key=items[next_index].key)


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


__all__ = [
    "TaskCheckpoint",
    "TaskItem",
    "TaskItemStatus",
    "TaskPlan",
    "TaskStateCoordinator",
    "TaskStateStore",
]
