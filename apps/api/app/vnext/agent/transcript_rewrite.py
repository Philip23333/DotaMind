"""Provider-neutral seams for deterministic transcript rewrites."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from app.vnext.llm.protocol import Message


@dataclass(frozen=True, slots=True)
class TranscriptRewriteEvent:
    """One observable replacement made to a transcript message."""

    kind: str
    tool_call_id: str
    reason: str
    metadata: dict[str, Any]


@dataclass(frozen=True, slots=True)
class TranscriptRewriteResult:
    """The rewritten transcript and the replacements that produced it."""

    messages: list[Message]
    events: list[TranscriptRewriteEvent]


class TranscriptRewriter(Protocol):
    """Rewrite a candidate transcript without owning runtime state."""

    def rewrite(self, messages: Sequence[Message]) -> TranscriptRewriteResult:
        """Return a fresh transcript and deterministic rewrite events."""


__all__ = [
    "TranscriptRewriteEvent",
    "TranscriptRewriteResult",
    "TranscriptRewriter",
]
