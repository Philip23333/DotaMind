"""Bounded admission for successful heavyweight tool observations."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class MaterializationDecision:
    """The result of one materialized observation admission attempt."""

    tool_call_id: str
    raw_bytes: int
    admitted: bool
    active_before_bytes: int
    active_after_bytes: int


class MaterializationBudget:
    """Track the active serialized bytes admitted during one runtime invocation."""

    def __init__(self, limit_bytes: int) -> None:
        if limit_bytes < 1:
            raise ValueError("materialization budget limit must be positive")
        self._limit_bytes = limit_bytes
        self._active: dict[str, int] = {}

    @property
    def limit_bytes(self) -> int:
        return self._limit_bytes

    @property
    def active_bytes(self) -> int:
        return sum(self._active.values())

    @property
    def active_count(self) -> int:
        return len(self._active)

    def admit(self, tool_call_id: str, *, raw_bytes: int) -> MaterializationDecision:
        if not tool_call_id:
            raise ValueError("materialization tool call ID must not be empty")
        if raw_bytes < 0:
            raise ValueError("materialization raw bytes must not be negative")
        before = self.active_bytes
        admitted = before + raw_bytes <= self._limit_bytes
        if admitted:
            self._active[tool_call_id] = raw_bytes
        return MaterializationDecision(
            tool_call_id=tool_call_id,
            raw_bytes=raw_bytes,
            admitted=admitted,
            active_before_bytes=before,
            active_after_bytes=self.active_bytes,
        )

    def release(self, tool_call_id: str) -> int:
        return self._active.pop(tool_call_id, 0)


__all__ = ["MaterializationBudget", "MaterializationDecision"]
