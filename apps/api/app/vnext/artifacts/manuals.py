"""Resolver for explicitly documented static artifact references."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from .store import ArtifactNotFoundError

DOCUMENTED_MANUAL_REFS: Mapping[str, str] = {}


class ManualResolver:
    """Resolve only an explicit allowlist of static documents."""

    def __init__(self, manual_directory: Path | None = None) -> None:
        self._manual_directory = manual_directory

    def read(self, ref: str) -> str:
        try:
            filename = DOCUMENTED_MANUAL_REFS[ref]
        except KeyError as exc:
            raise ArtifactNotFoundError(f"artifact not found: {ref}") from exc
        if self._manual_directory is None:
            raise ArtifactNotFoundError(f"artifact not found: {ref}")
        try:
            return (self._manual_directory / filename).read_text(encoding="utf-8")
        except FileNotFoundError as exc:
            raise ArtifactNotFoundError(f"artifact not found: {ref}") from exc


# Backward-compatible import name for generic artifact callers.
MANUAL_REFS = DOCUMENTED_MANUAL_REFS

__all__ = ["DOCUMENTED_MANUAL_REFS", "MANUAL_REFS", "ManualResolver"]
