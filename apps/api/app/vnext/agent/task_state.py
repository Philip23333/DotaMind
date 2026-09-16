"""Ephemeral task checkpoints and active artifact observation context."""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
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
        self._active_observations: dict[str, ArtifactObservation] = {}
        self._claimed_source_tool_call_ids: set[str] = set()

    def refresh(self, messages: Sequence[Message]) -> None:
        observations = collect_active_artifact_observations(messages)
        self._active_observations = {
            observation.tool_call_id: observation for observation in observations
            if observation.tool_call_id not in self._claimed_source_tool_call_ids
        }

    def create_checkpoint(
        self,
        key: str,
        value: dict[str, Any],
        source_tool_call_ids: Sequence[str],
    ) -> TaskCheckpoint:
        sources = tuple(source_tool_call_ids)
        self._validate_checkpoint(key, value, sources)
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
        return checkpoint

    def render_context(self) -> str | None:
        checkpoints = self.store.list()
        observations = list(self._active_observations.values())
        if not checkpoints and not observations:
            return None

        task_state = {checkpoint.key: checkpoint.value for checkpoint in checkpoints}
        manifest = [_manifest_item(observation) for observation in observations]
        return "\n\n".join(
            (
                "Task state:\n" + _json(task_state),
                "Checkpointable artifact observations:\n" + _json(manifest),
            )
        )

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


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


__all__ = ["TaskCheckpoint", "TaskStateCoordinator", "TaskStateStore"]
