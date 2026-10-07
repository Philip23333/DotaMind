"""Bounded, provider-neutral diagnostics for malformed model responses."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.vnext.llm.diagnostic_limits import ModelDiagnosticLimits

DiagnosticStage = Literal["tool_arguments_decode", "response_assembly", "stream_protocol"]
DiagnosticResponseMode = Literal["stream", "complete"]


class _DiagnosticModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ModelJSONErrorDiagnostic(_DiagnosticModel):
    message: str
    position: int | None
    line: int | None
    column: int | None


class ModelToolCallDiagnostic(_DiagnosticModel):
    index: int = Field(ge=0, strict=True)
    id: str | None
    provider_name: str | None
    agent_name: str | None
    argument_fragment_count: int | None = Field(default=None, ge=0, strict=True)
    arguments_utf8_bytes: int = Field(ge=0, strict=True)
    arguments_truncated: bool
    raw_arguments: str | None
    arguments_prefix: str | None
    arguments_suffix: str | None


class ModelFailureDiagnostics(_DiagnosticModel):
    schema_version: Literal[1] = 1
    stage: DiagnosticStage
    response_mode: DiagnosticResponseMode
    original_error_type: str
    finish_reason: str | None
    usage: dict[str, Any]
    stream_done_received: bool | None
    failed_tool_call_index: int | None = Field(default=None, ge=0, strict=True)
    tool_calls: tuple[ModelToolCallDiagnostic, ...]
    tool_calls_total: int = Field(ge=0, strict=True)
    tool_calls_truncated: bool
    json_error: ModelJSONErrorDiagnostic | None


@dataclass(frozen=True)
class ToolCallDiagnosticInput:
    """Adapter-supplied evidence before bounded serialization."""

    index: int
    call_id: str | None
    provider_name: str | None
    agent_name: str | None
    argument_fragments: tuple[str, ...] | None
    argument_fragment_count: int | None


def build_model_failure_diagnostics(
    *,
    stage: DiagnosticStage,
    response_mode: DiagnosticResponseMode,
    original_error_type: str,
    finish_reason: str | None,
    usage: Mapping[str, Any] | None,
    stream_done_received: bool | None,
    tool_calls: Sequence[ToolCallDiagnosticInput],
    limits: ModelDiagnosticLimits,
    failed_tool_call_index: int | None = None,
    json_error: ModelJSONErrorDiagnostic | None = None,
) -> ModelFailureDiagnostics:
    """Build a capped diagnostic while preserving complete byte counts."""

    ordered_calls = sorted(tool_calls, key=lambda call: call.index)
    selected_calls = ordered_calls[: limits.max_tool_calls]
    remaining_budget = limits.total_argument_max_bytes
    records: list[ModelToolCallDiagnostic] = []

    for call in selected_calls:
        fragments = call.argument_fragments
        byte_count = sum(len(_encode_arguments(fragment)) for fragment in fragments or ())
        truncated = byte_count > limits.argument_max_bytes or byte_count > remaining_budget

        raw_arguments: str | None = None
        prefix: str | None = None
        suffix: str | None = None
        if not truncated:
            raw_arguments = "".join(fragments) if fragments is not None else None
            remaining_budget -= byte_count
        elif remaining_budget > 0 and byte_count:
            snippet_budget = min(
                remaining_budget,
                limits.argument_edge_bytes * 2,
                byte_count,
            )
            prefix_budget = snippet_budget // 2
            suffix_budget = snippet_budget - prefix_budget
            prefix = _fragment_prefix(fragments or (), prefix_budget) or None
            suffix = _fragment_suffix(fragments or (), suffix_budget) or None
            retained_bytes = _encoded_size(prefix) + _encoded_size(suffix)
            remaining_budget -= retained_bytes

        records.append(
            ModelToolCallDiagnostic(
                index=call.index,
                id=call.call_id,
                provider_name=call.provider_name,
                agent_name=call.agent_name,
                argument_fragment_count=call.argument_fragment_count,
                arguments_utf8_bytes=byte_count,
                arguments_truncated=truncated,
                raw_arguments=raw_arguments,
                arguments_prefix=prefix,
                arguments_suffix=suffix,
            )
        )

    return ModelFailureDiagnostics(
        stage=stage,
        response_mode=response_mode,
        original_error_type=original_error_type,
        finish_reason=finish_reason,
        usage=deepcopy(dict(usage or {})),
        stream_done_received=stream_done_received,
        failed_tool_call_index=failed_tool_call_index,
        tool_calls=tuple(records),
        tool_calls_total=len(ordered_calls),
        tool_calls_truncated=len(ordered_calls) > limits.max_tool_calls,
        json_error=json_error,
    )


def _encode_arguments(value: str) -> bytes:
    # Provider JSON is Unicode text. Replacement keeps diagnostics best-effort
    # even for an escaped unpaired surrogate in an otherwise parseable response.
    return value.encode("utf-8", errors="replace")


def _fragment_prefix(fragments: Sequence[str], byte_limit: int) -> str:
    retained: list[bytes] = []
    remaining = byte_limit
    for fragment in fragments:
        if remaining <= 0:
            break
        encoded = _encode_arguments(fragment)
        retained.append(encoded[:remaining])
        remaining -= min(remaining, len(encoded))
    return b"".join(retained).decode("utf-8", errors="ignore")


def _fragment_suffix(fragments: Sequence[str], byte_limit: int) -> str:
    retained: list[bytes] = []
    remaining = byte_limit
    for fragment in reversed(fragments):
        if remaining <= 0:
            break
        encoded = _encode_arguments(fragment)
        retained.append(encoded[-remaining:])
        remaining -= min(remaining, len(encoded))
    return b"".join(reversed(retained)).decode("utf-8", errors="ignore")


def _encoded_size(value: str | None) -> int:
    return len(_encode_arguments(value)) if value is not None else 0


__all__ = [
    "DiagnosticResponseMode",
    "DiagnosticStage",
    "ModelFailureDiagnostics",
    "ModelJSONErrorDiagnostic",
    "ModelToolCallDiagnostic",
    "ToolCallDiagnosticInput",
    "build_model_failure_diagnostics",
]
