"""Stateless lifecycle management for artifact observations."""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import ValidationError

from app.vnext.agent.transcript_rewrite import (
    TranscriptRewriteEvent,
    TranscriptRewriteResult,
)
from app.vnext.llm.protocol import (
    AssistantMessage,
    Message,
    RejectedAssistantMessage,
    ToolResultMessage,
)

from .retrieval import ArtifactReadResult


@dataclass(frozen=True, slots=True)
class ArtifactObservation:
    """A validated model-visible artifact.read observation."""

    tool_call_id: str
    message_index: int
    ref: str
    path: str | None
    value: Any
    offset: int | None
    requested_limit: int | None
    actual_start: int | None
    actual_end: int | None
    kind: Literal["outline", "list_slice", "value"]


class ArtifactObservationTranscriptRewriter:
    """Replace duplicate or fully covered artifact.read results.

    The rewriter intentionally has no registry or cross-turn state.  Every call
    scans the complete candidate transcript, which keeps the operation
    deterministic and makes repeated application idempotent.
    """

    def __init__(self) -> None:
        self._request_start = 0

    def set_request_scope(self, message_index: int) -> None:
        self._request_start = max(0, message_index)

    def rewrite(self, messages: Sequence[Message]) -> TranscriptRewriteResult:
        original = list(messages)
        calls = _artifact_read_calls(original)
        observations = _artifact_observations(original, calls)
        replaced: dict[int, str] = {}
        events: list[TranscriptRewriteEvent] = []

        for old_index, old in observations:
            if old.message_index < self._request_start:
                continue
            for new_index, new in observations:
                if new_index <= old_index:
                    continue
                if new.message_index in replaced:
                    continue
                reason = _replacement_reason(old, new)
                if reason is None:
                    continue
                # The newest observation remains raw.  Only this earlier
                # message is replaced, even when it has already been covered
                # by another later observation.
                replaced[old.message_index] = reason
                events.append(
                    TranscriptRewriteEvent(
                        kind="artifact_observation",
                        tool_call_id=old.tool_call_id,
                        reason=reason,
                        metadata={
                            "source": _receipt_source(old),
                            **_rewrite_sizes(
                                original[old.message_index],
                                old,
                                reason,
                            ),
                        },
                    )
                )
                break

        if not replaced:
            return TranscriptRewriteResult(messages=original, events=[])

        rewritten: list[Message] = []
        for index, message in enumerate(original):
            replacement = replaced.get(index)
            if replacement is None or not isinstance(message, ToolResultMessage):
                rewritten.append(message)
                continue
            reason = replacement
            observation = next(
                observation
                for candidate_index, observation in observations
                if candidate_index == index
            )
            rewritten.append(
                message.model_copy(
                    update={
                        "content": _receipt(observation, reason)
                    }
                )
            )
        return TranscriptRewriteResult(messages=rewritten, events=events)


def _artifact_read_calls(messages: Sequence[Message]) -> dict[str, list[bool]]:
    calls: dict[str, list[bool]] = {}
    for message in messages:
        if isinstance(message, AssistantMessage):
            for call in message.tool_calls:
                calls.setdefault(call.id, []).append(call.name == "artifact.read")
        elif isinstance(message, RejectedAssistantMessage):
            for call in message.tool_calls:
                calls.setdefault(call.id, []).append(False)
    return calls


def _artifact_observations(
    messages: Sequence[Message],
    calls: dict[str, list[bool]],
) -> list[tuple[int, ArtifactObservation]]:
    observations: list[tuple[int, ArtifactObservation]] = []
    for message_index, message in enumerate(messages):
        if not isinstance(message, ToolResultMessage):
            continue
        call_kinds = calls.get(message.tool_call_id)
        is_artifact_read = call_kinds.pop(0) if call_kinds else False
        if message.status != "ok" or not is_artifact_read or _is_receipt(message.content):
            continue
        try:
            result = ArtifactReadResult.model_validate(message.content)
        except (ValidationError, TypeError, ValueError):
            continue
        kind: Literal["outline", "list_slice", "value"]
        if result.path is None:
            kind = "outline"
        elif isinstance(result.value, list):
            kind = "list_slice"
        else:
            kind = "value"
        if kind == "list_slice":
            actual_start = result.offset if result.offset is not None else 0
            actual_end = actual_start + len(result.value)
        else:
            actual_start = None
            actual_end = None
        observations.append(
            (
                message_index,
                ArtifactObservation(
                    tool_call_id=message.tool_call_id,
                    message_index=message_index,
                    ref=result.ref,
                    path=result.path,
                    value=result.value,
                    offset=result.offset,
                    requested_limit=result.limit,
                    actual_start=actual_start,
                    actual_end=actual_end,
                    kind=kind,
                ),
            )
        )
    return observations


def collect_active_artifact_observations(
    messages: Sequence[Message],
) -> list[ArtifactObservation]:
    """Return successful, raw artifact.read observations from a transcript."""

    return [
        observation
        for _, observation in _artifact_observations(messages, _artifact_read_calls(messages))
    ]


def _is_receipt(content: Any) -> bool:
    if not isinstance(content, dict):
        return False
    marker = content.get("_artifact_observation")
    return isinstance(marker, dict) and marker.get("state") == "receipt_only"


def _replacement_reason(
    old: ArtifactObservation,
    new: ArtifactObservation,
) -> str | None:
    if _is_exact_duplicate(old, new):
        return "duplicate"
    if _is_full_superset(old, new):
        return "superseded"
    return None


def _is_exact_duplicate(old: ArtifactObservation, new: ArtifactObservation) -> bool:
    return (
        old.ref == new.ref
        and old.path == new.path
        and old.kind == new.kind
        and old.actual_start == new.actual_start
        and old.actual_end == new.actual_end
        and old.value == new.value
    )


def _is_full_superset(old: ArtifactObservation, new: ArtifactObservation) -> bool:
    if (
        old.ref != new.ref
        or old.path != new.path
        or old.kind != "list_slice"
        or new.kind != "list_slice"
        or old.actual_start is None
        or old.actual_end is None
        or new.actual_start is None
        or new.actual_end is None
    ):
        return False
    if old.actual_start == new.actual_start and old.actual_end == new.actual_end:
        return False
    if new.actual_start > old.actual_start or new.actual_end < old.actual_end:
        return False
    start = old.actual_start - new.actual_start
    end = start + len(old.value)
    return new.value[start:end] == old.value


def _receipt_source(observation: ArtifactObservation) -> dict[str, Any]:
    source: dict[str, Any] = {"ref": observation.ref}
    if observation.kind != "outline":
        source["path"] = observation.path
        if observation.offset is not None:
            source["offset"] = observation.offset
        if observation.requested_limit is not None:
            source["limit"] = observation.requested_limit
    return source


def _receipt(
    observation: ArtifactObservation,
    reason: str,
) -> dict[str, Any]:
    marker: dict[str, Any] = {
        "state": "receipt_only",
        "reason": reason,
        "re_readable": True,
        "mode": "outline" if observation.kind == "outline" else "read",
        **_receipt_source(observation),
    }
    return {"_artifact_observation": marker}


def _rewrite_sizes(
    message: Message,
    observation: ArtifactObservation,
    reason: str,
) -> dict[str, int]:
    if not isinstance(message, ToolResultMessage):
        return {
            "message_index": observation.message_index,
            "raw_bytes": 0,
            "receipt_bytes": 0,
            "saved_bytes": 0,
        }
    raw_bytes = _serialized_size(message.model_dump(mode="json"))
    receipt = message.model_copy(
        update={
            "content": _receipt(
                observation,
                reason,
            )
        }
    )
    receipt_bytes = _serialized_size(receipt.model_dump(mode="json"))
    return {
        "message_index": observation.message_index,
        "raw_bytes": raw_bytes,
        "receipt_bytes": receipt_bytes,
        "saved_bytes": max(0, raw_bytes - receipt_bytes),
    }


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
    "ArtifactObservation",
    "ArtifactObservationTranscriptRewriter",
    "collect_active_artifact_observations",
]
