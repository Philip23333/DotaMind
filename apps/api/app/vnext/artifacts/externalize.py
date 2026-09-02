"""Shared size gate for full logical tool responses."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from .store import SessionArtifactStore

INLINE_TOOL_RESPONSE_MAX_BYTES = 12 * 1024


class ToolResponseArtifactError(RuntimeError):
    """Raised when an oversized logical tool response cannot be externalized."""


@dataclass(frozen=True)
class ExternalizedToolResponse:
    artifact_ref: str | None

    @property
    def spilled(self) -> bool:
        return self.artifact_ref is not None


def serialized_size(value: Any) -> int:
    return len(json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))


class ToolResponseExternalizer:
    """Keep small responses inline and spill complete large responses once."""

    def __init__(self, store: SessionArtifactStore) -> None:
        self._store = store

    async def externalize(self, response: Any) -> ExternalizedToolResponse:
        if serialized_size(response) <= INLINE_TOOL_RESPONSE_MAX_BYTES:
            return ExternalizedToolResponse(artifact_ref=None)
        try:
            return ExternalizedToolResponse(artifact_ref=await self._store.put(response))
        except Exception as exc:
            raise ToolResponseArtifactError("could not externalize tool response") from exc


__all__ = [
    "ExternalizedToolResponse",
    "INLINE_TOOL_RESPONSE_MAX_BYTES",
    "ToolResponseArtifactError",
    "ToolResponseExternalizer",
    "serialized_size",
]
