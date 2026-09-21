"""Data contracts for deterministic history-compaction range selection."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from app.vnext.llm.protocol import Message


@dataclass(frozen=True, slots=True)
class HistoryCompactionRange:
    """A safe split of one effective-history input snapshot.

    ``cut_index`` is an index into the input sequence used for this selection
    attempt. It is not an original execution-record position or a stable
    message identifier.
    """

    cut_index: int
    prefix_messages: tuple[Message, ...]
    retained_messages: tuple[Message, ...]
    retained_bytes: int


@dataclass(frozen=True, slots=True)
class CompactionSummaryResult:
    """One validated summary candidate returned by a maintenance call."""

    summary: str
    usage: dict[str, Any]
    duration_seconds: float

    def __post_init__(self) -> None:
        object.__setattr__(self, "usage", deepcopy(self.usage))


__all__ = ["CompactionSummaryResult", "HistoryCompactionRange"]
