"""Read the persistent catalog image manifest for answer presentation."""

from __future__ import annotations

import threading
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Literal

from app.vnext.data_updates.image_manifest import parse_image_manifest

ImageEntityKind = Literal["hero", "item", "ability"]
_KIND_TO_MANIFEST: dict[ImageEntityKind, str] = {
    "hero": "heroes",
    "item": "items",
    "ability": "abilities",
}


@dataclass(frozen=True, slots=True)
class ImageManifestEntry:
    kind: str
    entity_id: int
    internal_name: str
    content_sha256: str
    source_patch: str


@dataclass(frozen=True, slots=True)
class ImageManifestSnapshot:
    entries: Mapping[str, ImageManifestEntry]
    assets_directory: Path

    def image_url(
        self,
        *,
        kind: ImageEntityKind,
        entity_id: int,
        internal_name: str,
    ) -> str | None:
        manifest_kind = _KIND_TO_MANIFEST[kind]
        entry = self.entries.get(f"{manifest_kind}:{entity_id}")
        if entry is None or entry.internal_name != internal_name:
            return None
        asset_path = self.assets_directory / f"{entry.content_sha256}.png"
        if not asset_path.is_file():
            return None
        return f"/api/v1/assets/dota/by-hash/{entry.content_sha256}.png"


class ImageManifestReader:
    """Read once per match and retain the most recently validated manifest."""

    def __init__(self, data_root: Path) -> None:
        self._manifest_path = Path(data_root) / "images" / "manifest.json"
        self._assets_directory = Path(data_root) / "images" / "assets"
        self._lock = threading.Lock()
        self._last_valid: ImageManifestSnapshot | None = None
        self._empty = ImageManifestSnapshot(
            entries=MappingProxyType({}),
            assets_directory=self._assets_directory,
        )

    def read_current(self) -> ImageManifestSnapshot:
        """Return this read's valid manifest, or the last good/empty snapshot on failure."""

        with self._lock:
            try:
                entries = parse_image_manifest(self._manifest_path.read_bytes())
            except (OSError, UnicodeDecodeError, ValueError, TypeError, RecursionError):
                return self._last_valid if self._last_valid is not None else self._empty
            snapshot = ImageManifestSnapshot(
                entries=MappingProxyType(
                    {
                        key: ImageManifestEntry(**entry)
                        for key, entry in entries.items()
                    }
                ),
                assets_directory=self._assets_directory,
            )
            self._last_valid = snapshot
            return snapshot
