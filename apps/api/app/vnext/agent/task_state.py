"""Ephemeral task checkpoints and active artifact observation context."""

from __future__ import annotations

import json
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from typing import Any, Literal
from uuid import uuid4

from app.vnext.artifacts.lifecycle import (
    collect_active_artifact_observations,
)
from app.vnext.llm.protocol import AssistantMessage, Message, ToolCall, ToolResultMessage


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


@dataclass(frozen=True, slots=True)
class EvidenceLease:
    """Task-associated metadata for one materialized observation."""

    tool_call_id: str
    task_key: str
    raw_bytes: int


@dataclass(frozen=True, slots=True)
class CheckpointSource:
    """Small metadata record for one currently usable checkpoint source."""

    tool_call_id: str
    tool_name: str
    source_kind: Literal["inline_tool_result", "artifact_read"]
    message_index: int
    task_key: str | None = None
    ref: str | None = None
    path: str | None = None
    actual_start: int | None = None
    actual_end: int | None = None


@dataclass(frozen=True, slots=True)
class _InlineSourceOwner:
    tool_name: str
    task_key: str | None


class CheckpointSourceError(ValueError):
    """A recoverable checkpoint source validation failure."""

    def __init__(
        self,
        *,
        checkpoint_key: str,
        invalid_sources: Sequence[str],
        available_sources: Sequence[str],
        message: str,
    ) -> None:
        self.details = {
            "checkpoint_key": checkpoint_key,
            "invalid_sources": list(invalid_sources),
            "available_sources": list(available_sources),
        }
        super().__init__(message)


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

    def clear(self) -> None:
        self._checkpoints.clear()


class TaskStateCoordinator:
    """Coordinate ephemeral checkpoint state with the current raw observations."""

    def __init__(self, store: TaskStateStore | None = None) -> None:
        self.store = store or TaskStateStore()
        self.plan: TaskPlan | None = None
        self._active_sources: dict[str, CheckpointSource] = {}
        self._inline_source_owners: dict[str, _InlineSourceOwner] = {}
        self._claimed_source_tool_call_ids: set[str] = set()
        self._active_evidence_leases: dict[str, EvidenceLease] = {}
        self._request_start = 0

    def reset(self) -> None:
        """Clear request-local state while preserving handler references."""

        self.plan = None
        self.store.clear()
        self._active_sources.clear()
        self._inline_source_owners.clear()
        self._claimed_source_tool_call_ids.clear()
        self._active_evidence_leases.clear()
        self._request_start = 0

    def set_request_scope(self, message_index: int) -> None:
        self._request_start = max(0, message_index)

    def refresh(self, messages: Sequence[Message], *, start_index: int | None = None) -> None:
        effective_start = self._request_start if start_index is None else max(0, start_index)
        scoped_messages = messages[effective_start:]
        sources: dict[str, CheckpointSource] = {}
        for observation in collect_active_artifact_observations(scoped_messages):
            if observation.tool_call_id in self._claimed_source_tool_call_ids:
                continue
            sources[observation.tool_call_id] = CheckpointSource(
                tool_call_id=observation.tool_call_id,
                tool_name="artifact.read",
                source_kind="artifact_read",
                message_index=effective_start + observation.message_index,
                ref=observation.ref,
                path=observation.path,
                actual_start=observation.actual_start,
                actual_end=observation.actual_end,
            )

        inline_sources = _collect_active_inline_sources(
            scoped_messages,
            self._inline_source_owners,
            claimed_tool_call_ids=self._claimed_source_tool_call_ids,
            message_index_offset=effective_start,
        )
        sources.update((source.tool_call_id, source) for source in inline_sources)
        self._active_sources = sources
        active_inline_ids = {
            source.tool_call_id
            for source in inline_sources
        }
        self._inline_source_owners = {
            tool_call_id: owner
            for tool_call_id, owner in self._inline_source_owners.items()
            if tool_call_id in active_inline_ids
        }

    def record_inline_tool_result(
        self,
        call: ToolCall,
        result: ToolResultMessage,
        *,
        task_key: str | None,
    ) -> None:
        """Record execution-time ownership for one eligible successful inline result."""

        if (
            result.status != "ok"
            or call.id != result.tool_call_id
            or not _is_checkpointable_inline_tool(call.name)
            or not _is_checkpointable_inline_content(result.content)
        ):
            return
        self._inline_source_owners[call.id] = _InlineSourceOwner(
            tool_name=call.name,
            task_key=task_key,
        )

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

    def completed_materialization_task(self, task_key: str | None) -> dict[str, str] | None:
        """Return completed task metadata when materialization must be rejected."""

        if self.plan is None:
            return None
        resolved_key = task_key or self.plan.current_key
        if resolved_key is None:
            return None
        item = next((item for item in self.plan.items if item.key == resolved_key), None)
        if item is None or item.status is not TaskItemStatus.COMPLETED:
            return None
        return {"task_key": item.key, "state": item.status.value}

    def plan_snapshot(self) -> TaskPlan | None:
        """Return the immutable active-plan snapshot."""

        return self.plan

    def record_evidence_lease(
        self,
        tool_call_id: str,
        *,
        task_key: str | None,
        raw_bytes: int,
    ) -> None:
        """Associate one successful materializing observation with its intended item."""

        plan = self.plan
        current = self.current_item()
        if plan is None or current is None:
            return
        if not isinstance(tool_call_id, str) or not tool_call_id:
            raise ValueError("evidence lease tool call ID must not be empty")
        if raw_bytes < 0:
            raise ValueError("evidence lease raw bytes must not be negative")
        owner_key = current.key if task_key is None else task_key
        if not isinstance(owner_key, str) or not owner_key:
            raise ValueError("evidence lease task key must be a non-empty string")
        owner = next((item for item in plan.items if item.key == owner_key), None)
        if owner is None:
            raise ValueError("evidence lease task key is not in the active task plan: " + owner_key)
        if owner.status is TaskItemStatus.COMPLETED:
            raise ValueError("evidence lease task key is already completed: " + owner_key)
        self._active_evidence_leases[tool_call_id] = EvidenceLease(
            tool_call_id=tool_call_id,
            task_key=owner_key,
            raw_bytes=raw_bytes,
        )

    def active_evidence_lease(self) -> dict[str, Any] | None:
        """Return compact active lease accounting for trace telemetry."""

        if not self._active_evidence_leases:
            return None
        grouped: dict[str, list[EvidenceLease]] = {}
        for lease in self._active_evidence_leases.values():
            grouped.setdefault(lease.task_key, []).append(lease)
        if len(grouped) == 1:
            task_key, leases = next(iter(grouped.items()))
            return {
                "task_key": task_key,
                "observation_count": len(leases),
                "raw_bytes": sum(lease.raw_bytes for lease in leases),
            }
        return {
            "task_key": None,
            "observation_count": len(self._active_evidence_leases),
            "raw_bytes": sum(lease.raw_bytes for lease in self._active_evidence_leases.values()),
            "partitions": [
                {
                    "task_key": task_key,
                    "observation_count": len(leases),
                    "raw_bytes": sum(lease.raw_bytes for lease in leases),
                }
                for task_key, leases in sorted(grouped.items())
            ],
        }

    def active_evidence_leases_snapshot(self) -> list[dict[str, Any]]:
        """Return individual active leases for checkpoint lifecycle diagnostics."""

        return [
            {
                "tool_call_id": lease.tool_call_id,
                "task_key": lease.task_key,
                "raw_bytes": lease.raw_bytes,
            }
            for lease in sorted(
                self._active_evidence_leases.values(),
                key=lambda lease: lease.tool_call_id,
            )
        ]

    def retain_evidence_leases(self, tool_call_ids: Collection[str]) -> None:
        """Drop leases whose raw observations no longer remain in context."""

        retained = set(tool_call_ids)
        self._active_evidence_leases = {
            tool_call_id: lease
            for tool_call_id, lease in self._active_evidence_leases.items()
            if tool_call_id in retained
        }

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
            self._active_sources.pop(source, None)
        if self.plan is not None and self.plan.current_key is not None:
            completed_key = self.plan.current_key
            for tool_call_id, lease in list(self._active_evidence_leases.items()):
                if lease.task_key == completed_key:
                    self._active_evidence_leases.pop(tool_call_id)
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
            lines = [f"Task plan:\nCURRENT: {current}"]
            lines.extend(
                f"- {item['key']} [{item['status']}] {item['objective']}"
                for item in task_plan["items"]
            )
            sections.append("\n".join(lines))
        focus_context = _focus_context(
            self.plan,
            payload["checkpoint_candidates"],
            self._active_evidence_leases,
            self._ordered_active_sources(),
        )
        if focus_context is not None:
            sections.append(focus_context)
        sections.append("Task state:\n" + _json(payload["task_state"]))
        sections.append(
            "Checkpointable observations:\n"
            + _json(payload["active_manifest"])
        )
        sections.append("Checkpoint candidates:\n" + _json(payload["checkpoint_candidates"]))
        return "\n\n".join(sections)

    def context_payload(self) -> dict[str, Any]:
        """Return the structured ephemeral payload used by model context."""

        checkpoints = self.store.list()
        sources = self._ordered_active_sources()
        return {
            "task_plan": _plan_payload(self.plan),
            "task_state": {
                checkpoint.key: dict(checkpoint.value) for checkpoint in checkpoints
            },
            "active_manifest": [
                _manifest_item(
                    source,
                    task_key=self._source_task_key(source),
                    lease_key=(
                        self._active_evidence_leases[source.tool_call_id].task_key
                        if source.tool_call_id in self._active_evidence_leases
                        else None
                    ),
                )
                for source in sources
            ],
            "checkpoint_candidates": _checkpoint_candidates(
                self.plan,
                sources,
                self._active_evidence_leases,
            ),
        }

    def _ordered_active_sources(self) -> list[CheckpointSource]:
        return sorted(
            self._active_sources.values(),
            key=lambda source: (source.message_index, source.tool_call_id),
        )

    def _source_task_key(self, source: CheckpointSource) -> str | None:
        return _source_owner_key(source, self._active_evidence_leases)

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
            raise CheckpointSourceError(
                checkpoint_key=key,
                invalid_sources=claimed,
                available_sources=self._available_checkpoint_source_ids(key),
                message=(
                    "checkpoint sources have already been claimed: "
                    + ", ".join(claimed)
                ),
            )
        unknown = [
            tool_call_id
            for tool_call_id in source_tool_call_ids
            if tool_call_id not in self._active_sources
        ]
        if unknown:
            raise CheckpointSourceError(
                checkpoint_key=key,
                invalid_sources=unknown,
                available_sources=self._available_checkpoint_source_ids(key),
                message=(
                    "checkpoint sources must refer to active checkpointable "
                    "observations: "
                    + ", ".join(unknown)
                ),
            )
        mismatched = [
            tool_call_id
            for tool_call_id in source_tool_call_ids
            if (source := self._active_sources.get(tool_call_id)) is not None
            and (owner_key := self._source_task_key(source)) is not None
            and owner_key != key
        ]
        if mismatched:
            raise CheckpointSourceError(
                checkpoint_key=key,
                invalid_sources=mismatched,
                available_sources=self._available_checkpoint_source_ids(key),
                message=(
                    "checkpoint sources are leased to different task items: "
                    + ", ".join(mismatched)
                ),
            )

    def _available_checkpoint_source_ids(self, key: str) -> list[str]:
        return [
            source.tool_call_id
            for source in self._ordered_active_sources()
            if self._source_task_key(source) in (None, key)
        ]


def _manifest_item(
    source: CheckpointSource,
    *,
    task_key: str | None,
    lease_key: str | None,
) -> dict[str, Any]:
    item: dict[str, Any] = {
        "tool_call_id": source.tool_call_id,
        "tool_name": source.tool_name,
        "source_kind": source.source_kind,
    }
    if source.source_kind == "artifact_read":
        item["ref"] = source.ref
        item["path"] = source.path
        if source.actual_start is not None:
            item["actual_start"] = source.actual_start
        if source.actual_end is not None:
            item["actual_end"] = source.actual_end
        if lease_key is not None:
            item["lease_key"] = lease_key
    else:
        item["task_key"] = task_key
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


def _checkpoint_candidates(
    plan: TaskPlan | None,
    sources: Sequence[CheckpointSource],
    leases: Mapping[str, EvidenceLease],
) -> list[dict[str, Any]]:
    """Project active sources whose execution-time owner permits current use."""

    if plan is not None and plan.current_key is None:
        return []
    current_key = plan.current_key if plan is not None else None
    candidates: list[dict[str, Any]] = []
    for source in sources:
        lease = leases.get(source.tool_call_id)
        owner_key = _source_owner_key(source, leases)
        if owner_key is not None and owner_key != current_key:
            continue
        candidate: dict[str, Any] = {
            "tool_call_id": source.tool_call_id,
            "tool_name": source.tool_name,
            "source_kind": source.source_kind,
            "task_key": owner_key,
            "status": (
                "ACTIVE_RAW"
                if source.source_kind == "artifact_read"
                else "ACTIVE_INLINE"
            ),
        }
        if lease is not None:
            candidate["bytes"] = lease.raw_bytes
        candidates.append(candidate)
    return candidates


def _collect_active_inline_sources(
    messages: Sequence[Message],
    owners: Mapping[str, _InlineSourceOwner],
    *,
    claimed_tool_call_ids: Collection[str],
    message_index_offset: int,
) -> list[CheckpointSource]:
    calls: dict[str, list[ToolCall]] = {}
    sources: list[CheckpointSource] = []
    for message_index, message in enumerate(messages):
        if isinstance(message, AssistantMessage):
            for call in message.tool_calls:
                calls.setdefault(call.id, []).append(call)
            continue
        if not isinstance(message, ToolResultMessage):
            continue
        matching_calls = calls.get(message.tool_call_id)
        call = matching_calls.pop(0) if matching_calls else None
        owner = owners.get(message.tool_call_id)
        if (
            call is None
            or owner is None
            or message.tool_call_id in claimed_tool_call_ids
            or message.status != "ok"
            or call.name != owner.tool_name
            or not _is_checkpointable_inline_tool(call.name)
            or not _is_checkpointable_inline_content(message.content)
        ):
            continue
        sources.append(
            CheckpointSource(
                tool_call_id=message.tool_call_id,
                tool_name=call.name,
                source_kind="inline_tool_result",
                message_index=message_index_offset + message_index,
                task_key=owner.task_key,
            )
        )
    return sources


def _is_checkpointable_inline_tool(tool_name: str) -> bool:
    return (
        tool_name not in {"artifact.read", "artifact.grep"}
        and not tool_name.startswith("task.")
    )


def _is_checkpointable_inline_content(content: Any) -> bool:
    if not isinstance(content, (dict, list)):
        return True
    if isinstance(content, dict):
        if content.get("externalized") is True or "artifact_ref" in content:
            return False
        observation = content.get("_artifact_observation")
        if isinstance(observation, dict) and observation.get("state") == "receipt_only":
            return False
        materialization = content.get("_context_materialization")
        if isinstance(materialization, dict) and materialization.get("state") == "deferred":
            return False
    stack = list(content.values()) if isinstance(content, dict) else list(content)
    while stack:
        value = stack.pop()
        if isinstance(value, dict):
            if "_artifact_path" in value:
                return False
            stack.extend(value.values())
        elif isinstance(value, list):
            stack.extend(value)
    return True


def _source_owner_key(
    source: CheckpointSource,
    leases: Mapping[str, EvidenceLease],
) -> str | None:
    if source.source_kind == "artifact_read":
        lease = leases.get(source.tool_call_id)
        return lease.task_key if lease is not None else None
    return source.task_key


def _focus_context(
    plan: TaskPlan | None,
    checkpoint_candidates: Sequence[Mapping[str, Any]],
    leases: Mapping[str, EvidenceLease],
    sources: Sequence[CheckpointSource],
) -> str | None:
    if plan is None or plan.current_key is None:
        return None

    current_key = plan.current_key
    current = next(
        (item for item in plan.items if item.key == current_key),
        None,
    )
    if current is None:
        return None

    candidate_bytes = sum(
        int(candidate.get("bytes", 0))
        for candidate in checkpoint_candidates
        if candidate.get("task_key") == current_key
    )
    future_sources = [
        source
        for source in sources
        if (owner_key := _source_owner_key(source, leases)) is not None
        and owner_key != current_key
    ]

    lines = [
        "Task focus:",
        f"CURRENT: {current.key}",
        f"Objective: {current.objective}",
        "CURRENT is the primary execution focus, not an exclusive scope.",
        (
            "Prioritize actions that materially advance CURRENT. Later pending "
            "items may be explored opportunistically, but should not displace "
            "progress on CURRENT."
        ),
        (
            "Preserve CURRENT's established entity, time, version, edition, and "
            "competition constraints in downstream queries whenever available "
            "tool fields can express them."
        ),
        "",
        "Current progress:",
        f"checkpoint_candidates: {len(checkpoint_candidates)}",
        f"checkpoint_candidate_bytes: {candidate_bytes}",
        f"future_owned_active_observations: {len(future_sources)}",
    ]

    if checkpoint_candidates:
        lines.extend(
            [
                "",
                (
                    "CURRENT has checkpointable observations. If they already "
                    "satisfy the objective, checkpoint them. Otherwise gather "
                    "the specifically missing evidence needed to complete it."
                ),
            ]
        )

    if future_sources:
        lines.extend(
            [
                "",
                (
                    "Later-task evidence is already active while CURRENT remains "
                    "incomplete. Avoid expanding later tasks unless doing so also "
                    "materially advances CURRENT or the evidence is obtained "
                    "incidentally by an efficient bounded request."
                ),
            ]
        )

    return "\n".join(lines)


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
    "CheckpointSourceError",
    "CheckpointSource",
    "EvidenceLease",
    "TaskCheckpoint",
    "TaskItem",
    "TaskItemStatus",
    "TaskPlan",
    "TaskStateCoordinator",
    "TaskStateStore",
]
