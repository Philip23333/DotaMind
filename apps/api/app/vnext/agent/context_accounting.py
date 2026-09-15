"""Deterministic accounting for one provider-neutral model context."""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from app.vnext.llm.protocol import Message, ModelRequest

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
    tool_schemas: ContextSectionUsage
    runtime_prompt: RuntimePromptUsage
    effective_request: EffectiveRequestUsage

    def to_dict(self) -> dict[str, Any]:
        return {
            "measurement": MEASUREMENT,
            "stable_messages": self.stable_messages.to_dict(),
            "tool_schemas": self.tool_schemas.to_dict(),
            "runtime_prompt": self.runtime_prompt.to_dict(),
            "effective_request": self.effective_request.to_dict(),
        }


def build_context_accounting(
    request: ModelRequest,
    *,
    stable_messages: Sequence[Message] | None = None,
) -> ContextAccounting:
    """Measure the logical context visible to one model invocation.

    ``stable_messages`` excludes the ephemeral Runtime Prompt. When it is
    omitted, the request transcript is treated as entirely stable and the
    Runtime Prompt contribution is reported as zero.
    """

    stable = list(request.messages if stable_messages is None else stable_messages)
    stable_payloads = [_model_payload(message) for message in stable]
    effective_payloads = [_model_payload(message) for message in request.messages]
    tool_payloads = [_model_payload(tool) for tool in request.tools]

    by_role_payloads: dict[str, list[dict[str, Any]]] = {}
    for message, payload in zip(stable, stable_payloads, strict=True):
        by_role_payloads.setdefault(message.role, []).append(payload)

    stable_bytes = _sum_serialized_bytes(stable_payloads)
    effective_message_bytes = _sum_serialized_bytes(effective_payloads)
    runtime_prompt_present = stable_payloads != effective_payloads

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
        tool_schemas=ContextSectionUsage(
            count=len(tool_payloads),
            serialized_bytes=_sum_serialized_bytes(tool_payloads),
        ),
        runtime_prompt=RuntimePromptUsage(
            present=runtime_prompt_present,
            serialized_bytes=(
                max(0, effective_message_bytes - stable_bytes)
                if runtime_prompt_present
                else 0
            ),
        ),
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
    "build_context_accounting",
]
