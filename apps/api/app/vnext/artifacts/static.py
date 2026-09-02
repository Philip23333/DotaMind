"""Explicit read-only generated documents available through artifact retrieval."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from .store import ArtifactNotFoundError

_REPOSITORY_ROOT = Path(__file__).resolve().parents[5]
_PANDASCORE_MANUAL_DIRECTORY = (
    _REPOSITORY_ROOT / "docs" / "reference" / "pandascore-generated" / "agent-manual"
)

PANDASCORE_MANUAL_REFS: Mapping[str, str] = {
    "manual:pandascore:index": "INDEX.md",
    "manual:pandascore:league": "league.md",
    "manual:pandascore:serie": "serie.md",
    "manual:pandascore:tournament": "tournament.md",
    "manual:pandascore:match": "match.md",
    "manual:pandascore:team": "team.md",
    "manual:pandascore:player": "player.md",
}


class StaticArtifactResolver:
    """Resolve the small allowlist of generated PandaScore manuals."""

    def __init__(self, manual_directory: Path = _PANDASCORE_MANUAL_DIRECTORY) -> None:
        self._manual_directory = manual_directory

    def read(self, ref: str) -> str:
        try:
            filename = PANDASCORE_MANUAL_REFS[ref]
        except KeyError as exc:
            raise ArtifactNotFoundError(f"artifact not found: {ref}") from exc

        try:
            return (self._manual_directory / filename).read_text(encoding="utf-8")
        except FileNotFoundError as exc:
            raise ArtifactNotFoundError(f"artifact not found: {ref}") from exc


__all__ = ["PANDASCORE_MANUAL_REFS", "StaticArtifactResolver"]
