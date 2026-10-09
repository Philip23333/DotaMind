"""Read stable display references from the local Valve and Team directories."""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from app.integrations.valve.catalog_repository import (
    CatalogLookupError,
    DotaCatalogRepository,
)
from app.vnext.data_updates.image_reader import (
    ImageManifestReader,
    ImageManifestSnapshot,
)
from app.vnext.data_updates.team_directory_store import (
    TeamDirectorySnapshot,
    TeamDirectoryStore,
)

DisplaySource = Literal["valve", "pandascore"]
DisplayKind = Literal["hero", "item", "ability", "team"]
_SOURCE_BY_KIND: dict[DisplayKind, DisplaySource] = {
    "hero": "valve",
    "item": "valve",
    "ability": "valve",
    "team": "pandascore",
}
_DISPLAY_REF = re.compile(
    r"display:(?P<source>valve|pandascore):"
    r"(?P<kind>hero|item|ability|team):(?P<entity_id>[1-9][0-9]*)\Z",
    re.ASCII,
)


@dataclass(frozen=True, slots=True)
class EntityIdentity:
    """A source-qualified identity already known by a capability."""

    source: DisplaySource
    kind: DisplayKind
    entity_id: int

    def __post_init__(self) -> None:
        if not isinstance(self.source, str) or self.source not in {"valve", "pandascore"}:
            raise ValueError("unsupported display source")
        if not isinstance(self.kind, str) or self.kind not in _SOURCE_BY_KIND:
            raise ValueError("unsupported display entity kind")
        if self.source != _SOURCE_BY_KIND[self.kind]:
            raise ValueError("display source does not match entity kind")
        if type(self.entity_id) is not int or self.entity_id <= 0:
            raise ValueError("display entity ID must be a positive integer")


@dataclass(frozen=True, slots=True)
class DisplayEntity:
    display_ref: str
    kind: DisplayKind
    label: str
    image_url: str | None


def make_display_ref(identity: EntityIdentity) -> str:
    """Format a canonical reference from a validated explicit identity."""

    if not isinstance(identity, EntityIdentity):
        raise TypeError("identity must be an EntityIdentity")
    return f"display:{identity.source}:{identity.kind}:{identity.entity_id}"


def parse_display_ref(value: object) -> EntityIdentity | None:
    """Parse only the four supported, canonical source/type/ID combinations."""

    if not isinstance(value, str):
        return None
    match = _DISPLAY_REF.fullmatch(value)
    if match is None:
        return None
    try:
        return EntityIdentity(
            source=match.group("source"),  # type: ignore[arg-type]
            kind=match.group("kind"),  # type: ignore[arg-type]
            entity_id=int(match.group("entity_id")),
        )
    except (TypeError, ValueError):
        return None


class EntityDisplayDirectory:
    """Resolve explicit references using one read-only local snapshot per call."""

    def __init__(
        self,
        catalog_repository_provider: Callable[[], DotaCatalogRepository],
        *,
        data_root: Path | None = None,
        image_manifest_reader: ImageManifestReader | None = None,
    ) -> None:
        self._catalog_repository_provider = catalog_repository_provider
        self._image_manifest_reader = image_manifest_reader or (
            ImageManifestReader(data_root) if data_root is not None else None
        )
        self._team_reader = (
            TeamDirectoryStore(data_root) if data_root is not None else None
        )

    def reference_for(self, identity: EntityIdentity) -> str | None:
        """Return a reference only when the explicitly identified entity exists."""

        if not isinstance(identity, EntityIdentity):
            return None
        resolved = self._resolve_identities((identity,))
        return resolved[0].display_ref if resolved else None

    def resolve_many(self, refs: Iterable[str]) -> dict[str, DisplayEntity]:
        """Resolve unique canonical references; omit malformed and missing entities."""

        identities: dict[str, EntityIdentity] = {}
        for ref in refs:
            if not isinstance(ref, str) or ref in identities:
                continue
            identity = parse_display_ref(ref)
            if identity is not None:
                identities[ref] = identity
        if not identities:
            return {}

        resolved_by_identity = {
            entity.display_ref: entity
            for entity in self._resolve_identities(identities.values())
        }
        return {
            ref: resolved_by_identity[ref]
            for ref in identities
            if ref in resolved_by_identity
        }

    def _resolve_identities(
        self, identities: Iterable[EntityIdentity]
    ) -> list[DisplayEntity]:
        identity_list = list(identities)
        if not identity_list:
            return []

        needs_valve = any(identity.source == "valve" for identity in identity_list)
        catalog = self._catalog_repository_provider() if needs_valve else None
        image_manifest = (
            self._image_manifest_reader.read_current()
            if needs_valve and self._image_manifest_reader is not None
            else None
        )
        team_snapshot = (
            self._team_reader.read_current()
            if self._team_reader is not None
            and any(identity.source == "pandascore" for identity in identity_list)
            else None
        )

        result: list[DisplayEntity] = []
        for identity in identity_list:
            entity = self._resolve_one(
                identity,
                catalog=catalog,
                image_manifest=image_manifest,
                team_snapshot=team_snapshot,
            )
            if entity is not None:
                result.append(entity)
        return result

    @staticmethod
    def _resolve_one(
        identity: EntityIdentity,
        *,
        catalog: DotaCatalogRepository | None,
        image_manifest: ImageManifestSnapshot | None,
        team_snapshot: TeamDirectorySnapshot | None,
    ) -> DisplayEntity | None:
        display_ref = make_display_ref(identity)
        if identity.source == "pandascore":
            team = team_snapshot.teams.get(identity.entity_id) if team_snapshot else None
            if team is None:
                return None
            return DisplayEntity(
                display_ref=display_ref,
                kind="team",
                label=team.label,
                image_url=team_snapshot.image_url(team),
            )

        if catalog is None:
            return None
        try:
            if identity.kind == "hero":
                record = catalog.get_hero(identity.entity_id)
                internal_name = record.internal_name
                label = _catalog_label(record.name_zh, record.name_en, internal_name)
                image_kind: Literal["hero", "item", "ability"] = "hero"
            elif identity.kind == "item":
                record = catalog.get_item(identity.entity_id)
                internal_name = record.internal_name
                label = _catalog_label(record.name_zh, record.name_en, internal_name)
                image_kind = "item"
            else:
                record = catalog.get_ability(identity.entity_id)
                internal_name = record.internal_name
                label = _catalog_label(record.name_zh, record.name_en, internal_name)
                image_kind = "ability"
        except CatalogLookupError:
            return None

        image_url = (
            image_manifest.image_url(
                kind=image_kind,
                entity_id=identity.entity_id,
                internal_name=internal_name,
            )
            if image_manifest is not None
            else None
        )
        return DisplayEntity(
            display_ref=display_ref,
            kind=identity.kind,
            label=label,
            image_url=image_url,
        )


def _catalog_label(name_zh: str | None, name_en: str | None, internal_name: str) -> str:
    """Use the existing Chinese-then-English display-name preference."""

    for value in (name_zh, name_en, internal_name):
        if isinstance(value, str) and value.strip():
            return value.strip()
    return internal_name


__all__ = [
    "DisplayEntity",
    "EntityDisplayDirectory",
    "EntityIdentity",
    "make_display_ref",
    "parse_display_ref",
]
