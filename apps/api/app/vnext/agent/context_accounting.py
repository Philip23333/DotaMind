"""Deterministic accounting for one provider-neutral model context."""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from app.vnext.llm.protocol import AssistantMessage, Message, ModelRequest, ToolResultMessage

MEASUREMENT = "canonical_json_utf8_bytes"


@dataclass(frozen=True)
class ContextSectionUsage:
    count: int
    serialized_bytes: int

    def to_dict(self) -> dict[str, int]:
        return {
            "count": self.count,
            "serialized_bytes": self.serialized_bytes,
        }


@dataclass(frozen=True)
class StableMessagesUsage(ContextSectionUsage):
    by_role: dict[str, ContextSectionUsage]

    def to_dict(self) -> dict[str, Any]:
        return {
            **super().to_dict(),
            "by_role": {
                role: usage.to_dict() for role, usage in sorted(self.by_role.items())
            },
        }


@dataclass(frozen=True)
class RuntimePromptUsage:
    present: bool
    serialized_bytes: int

    def to_dict(self) -> dict[str, bool | int]:
        return {
            "present": self.present,
            "serialized_bytes": self.serialized_bytes,
        }


@dataclass(frozen=True)
class TaskContextUsage:
    present: bool
    serialized_bytes: int
    task_state: ContextSectionUsage
    active_manifest: ContextSectionUsage

    def to_dict(self) -> dict[str, Any]:
        return {
            "present": self.present,
            "serialized_bytes": self.serialized_bytes,
            "task_state": self.task_state.to_dict(),
            "active_manifest": self.active_manifest.to_dict(),
        }


@dataclass(frozen=True)
class ArtifactObservationsUsage:
    active_raw: ContextSectionUsage
    receipts: ContextSectionUsage

    def to_dict(self) -> dict[str, Any]:
        return {
            "active_raw": self.active_raw.to_dict(),
            "receipts": self.receipts.to_dict(),
        }


@dataclass(frozen=True)
class EffectiveRequestUsage:
    message_count: int
    tool_count: int
    serialized_bytes: int

    def to_dict(self) -> dict[str, int]:
        return {
            "message_count": self.message_count,
            "tool_count": self.tool_count,
            "serialized_bytes": self.serialized_bytes,
        }


@dataclass(frozen=True)
class ContextAccounting:
    stable_messages: StableMessagesUsage
    task_context: TaskContextUsage
    tool_schemas: ContextSectionUsage
    runtime_prompt: RuntimePromptUsage
    artifact_observations: ArtifactObservationsUsage
    effective_request: EffectiveRequestUsage

    def to_dict(self) -> dict[str, Any]:
        return {
            "measurement": MEASUREMENT,
            "stable_messages": self.stable_messages.to_dict(),
            "task_context": self.task_context.to_dict(),
            "tool_schemas": self.tool_schemas.to_dict(),
            "runtime_prompt": self.runtime_prompt.to_dict(),
            "artifact_observations": self.artifact_observations.to_dict(),
            "effective_request": self.effective_request.to_dict(),
        }


def build_context_accounting(
    request: ModelRequest,
    *,
    stable_messages: Sequence[Message] | None = None,
    task_context_messages: Sequence[Message] | None = None,
    task_context_payload: dict[str, Any] | None = None,
) -> ContextAccounting:
    """Measure the logical context visible to one model invocation.

    ``stable_messages`` excludes ephemeral Task Context and Runtime Prompt.
    ``task_context_messages`` includes Task Context but excludes Runtime Prompt.
    When either value is omitted, the preceding transcript boundary is used.
    """

    stable = list(request.messages if stable_messages is None else stable_messages)
    task_context = list(
        stable if task_context_messages is None else task_context_messages
    )
    stable_payloads = [_model_payload(message) for message in stable]
    task_context_payloads = [_model_payload(message) for message in task_context]
    effective_payloads = [_model_payload(message) for message in request.messages]
    tool_payloads = [_model_payload(tool) for tool in request.tools]

    by_role_payloads: dict[str, list[dict[str, Any]]] = {}
    for message, payload in zip(stable, stable_payloads, strict=True):
        by_role_payloads.setdefault(message.role, []).append(payload)

    stable_bytes = _sum_serialized_bytes(stable_payloads)
    task_context_bytes = _sum_serialized_bytes(task_context_payloads)
    effective_message_bytes = _sum_serialized_bytes(effective_payloads)
    task_context_present = task_context_payloads != stable_payloads
    runtime_prompt_present = task_context_payloads != effective_payloads
    payload = task_context_payload or {}
    task_state = payload.get("task_state", {})
    active_manifest = payload.get("active_manifest", [])
    task_state_bytes = (
        _serialized_size(task_state)
        if task_context_present and isinstance(task_state, dict)
        else 0
    )
    active_manifest_bytes = (
        _serialized_size(active_manifest)
        if task_context_present and isinstance(active_manifest, list)
        else 0
    )
    artifact_observations = _artifact_observation_usage(stable)

    return ContextAccounting(
        stable_messages=StableMessagesUsage(
            count=len(stable_payloads),
            serialized_bytes=stable_bytes,
            by_role={
                role: ContextSectionUsage(
                    count=len(payloads),
                    serialized_bytes=_sum_serialized_bytes(payloads),
                )
                for role, payloads in by_role_payloads.items()
            },
        ),
        task_context=TaskContextUsage(
            present=task_context_present,
            serialized_bytes=(
                max(0, task_context_bytes - stable_bytes)
                if task_context_present
                else 0
            ),
            task_state=ContextSectionUsage(
                count=len(task_state) if isinstance(task_state, dict) else 0,
                serialized_bytes=task_state_bytes,
            ),
            active_manifest=ContextSectionUsage(
                count=len(active_manifest) if isinstance(active_manifest, list) else 0,
                serialized_bytes=active_manifest_bytes,
            ),
        ),
        tool_schemas=ContextSectionUsage(
            count=len(tool_payloads),
            serialized_bytes=_sum_serialized_bytes(tool_payloads),
        ),
        runtime_prompt=RuntimePromptUsage(
            present=runtime_prompt_present,
            serialized_bytes=(
                max(0, effective_message_bytes - task_context_bytes)
                if runtime_prompt_present
                else 0
            ),
        ),
        artifact_observations=artifact_observations,
        effective_request=EffectiveRequestUsage(
            message_count=len(effective_payloads),
            tool_count=len(tool_payloads),
            serialized_bytes=_serialized_size(
                {"messages": effective_payloads, "tools": tool_payloads}
            ),
        ),
    )


def _model_payload(value: Any) -> dict[str, Any]:
    return value.model_dump(mode="json")


def _sum_serialized_bytes(values: Sequence[Any]) -> int:
    return sum(_serialized_size(value) for value in values)


def _artifact_observation_usage(
    messages: Sequence[Message],
) -> ArtifactObservationsUsage:
    artifact_read_call_ids = {
        call.id
        for message in messages
        if isinstance(message, AssistantMessage)
        for call in message.tool_calls
        if call.name == "artifact.read"
    }
    active_raw_count = 0
    active_raw_bytes = 0
    receipt_count = 0
    receipt_bytes = 0
    for message in messages:
        if (
            not isinstance(message, ToolResultMessage)
            or message.status != "ok"
            or message.tool_call_id not in artifact_read_call_ids
        ):
            continue
        serialized_bytes = _serialized_size(_model_payload(message))
        if _is_receipt(message.content):
            receipt_count += 1
            receipt_bytes += serialized_bytes
        else:
            active_raw_count += 1
            active_raw_bytes += serialized_bytes
    return ArtifactObservationsUsage(
        active_raw=ContextSectionUsage(active_raw_count, active_raw_bytes),
        receipts=ContextSectionUsage(receipt_count, receipt_bytes),
    )


def _is_receipt(content: Any) -> bool:
    if not isinstance(content, dict):
        return False
    marker = content.get("_artifact_observation")
    return isinstance(marker, dict) and marker.get("state") == "receipt_only"


def _serialized_size(value: Any) -> int:
    return len(
        json.dumps(
            value,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    )


__all__ = [
    "ContextAccounting",
    "ContextSectionUsage",
    "EffectiveRequestUsage",
    "MEASUREMENT",
    "RuntimePromptUsage",
    "StableMessagesUsage",
    "TaskContextUsage",
    "ArtifactObservationsUsage",
    "build_context_accounting",
]
