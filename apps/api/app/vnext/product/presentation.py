"""Deterministic local-catalog visual enrichment for product chat answers."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.integrations.valve.catalog_repository import (
    CATALOG_DIR,
    DotaCatalogRepository,
    load_default_catalog_repository,
)
from app.vnext.data_updates.image_reader import ImageManifestReader, ImageManifestSnapshot

_LOCAL_ASSET_PREFIX = "/api/v1/assets/"
_TEAM_MANIFEST_PATH = (
    Path(__file__).resolve().parents[2] / "data" / "esports" / "teams" / "manifest.json"
)


class ProductVisualEntity(BaseModel):
    """A local visual entity consumed by the existing chat Markdown decorator."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["hero", "item", "ability", "team"]
    imagePath: str
    label: str
    names: list[str] = Field(min_length=1)


@dataclass(frozen=True)
class _Mention:
    start: int
    end: int
    entity: ProductVisualEntity


@dataclass(frozen=True)
class _CatalogVisualDescriptor:
    kind: Literal["hero", "item", "ability"]
    entity_id: int
    internal_name: str
    names: tuple[str, ...]


class DotaVisualEntityEnricher:
    """Match Final text against the current local catalog and team-asset names."""

    def __init__(
        self,
        catalog_repository_provider: Callable[[], DotaCatalogRepository] | None = None,
        image_manifest_reader: ImageManifestReader | None = None,
    ) -> None:
        self._catalog_repository_provider = (
            catalog_repository_provider
            if catalog_repository_provider is not None
            else load_default_catalog_repository
        )
        self._image_manifest_reader = image_manifest_reader
        self._catalog_repository: DotaCatalogRepository | None = None
        self._catalog_entities: tuple[_CatalogVisualDescriptor, ...] = ()
        self._team_entities = tuple(_team_entities())

    def _descriptors_for(
        self, catalog: DotaCatalogRepository
    ) -> tuple[_CatalogVisualDescriptor, ...]:
        if catalog is not self._catalog_repository:
            self._catalog_entities = tuple(_catalog_descriptors(catalog))
            self._catalog_repository = catalog
        return self._catalog_entities

    def match(self, text: str) -> list[ProductVisualEntity]:
        """Return one local entity per longest, non-overlapping text match."""

        repository = self._catalog_repository_provider()
        descriptors = self._descriptors_for(repository)
        image_manifest = (
            self._image_manifest_reader.read_current()
            if self._image_manifest_reader is not None
            else None
        )
        catalog_entities = tuple(
            entity
            for descriptor in descriptors
            if (
                entity := _render_catalog_descriptor(
                    descriptor,
                    image_manifest=image_manifest,
                )
            )
            is not None
        )
        entities = catalog_entities + self._team_entities
        mentions: list[_Mention] = []
        for entity in entities:
            for name in entity.names:
                mentions.extend(_find_mentions(text, name, entity))

        selected: list[ProductVisualEntity] = []
        seen_paths: set[str] = set()
        occupied_until = -1
        for mention in sorted(
            mentions,
            key=lambda value: (value.start, -(value.end - value.start), value.entity.imagePath),
        ):
            if mention.start < occupied_until:
                continue
            occupied_until = mention.end
            if mention.entity.imagePath not in seen_paths:
                selected.append(mention.entity)
                seen_paths.add(mention.entity.imagePath)
        return selected


def _catalog_descriptors(catalog: DotaCatalogRepository) -> list[_CatalogVisualDescriptor]:
    entities: list[_CatalogVisualDescriptor] = []
    for hero in catalog.list_heroes():
        entity = _catalog_descriptor(
            kind="hero",
            entity_id=hero.hero_id,
            internal_name=hero.internal_name,
            name_zh=hero.name_zh,
            name_en=hero.name_en,
            aliases=hero.aliases,
        )
        if entity is not None:
            entities.append(entity)
    for item in catalog.list_items():
        if item.is_recipe:
            continue
        entity = _catalog_descriptor(
            kind="item",
            entity_id=item.item_id,
            internal_name=item.internal_name,
            name_zh=item.name_zh,
            name_en=item.name_en,
            aliases=item.aliases,
        )
        if entity is not None:
            entities.append(entity)
    for ability in catalog.list_abilities():
        if ability.is_item or ability.is_talent or ability.is_innate:
            continue
        entity = _catalog_descriptor(
            kind="ability",
            entity_id=ability.ability_id,
            internal_name=ability.internal_name,
            name_zh=ability.name_zh,
            name_en=ability.name_en,
        )
        if entity is not None:
            entities.append(entity)
    return entities


def _catalog_descriptor(
    *,
    kind: Literal["hero", "item", "ability"],
    entity_id: int,
    internal_name: str,
    name_zh: str | None,
    name_en: str | None,
    aliases: list[str] | None = None,
) -> _CatalogVisualDescriptor | None:
    names = _distinct_names(name_zh, name_en, *(aliases or ()))
    if not names:
        return None
    return _CatalogVisualDescriptor(kind, entity_id, internal_name, tuple(names))


def _render_catalog_descriptor(
    descriptor: _CatalogVisualDescriptor,
    *,
    image_manifest: ImageManifestSnapshot | None,
) -> ProductVisualEntity | None:
    if image_manifest is not None:
        image_path = image_manifest.image_url(
            kind=descriptor.kind,
            entity_id=descriptor.entity_id,
            internal_name=descriptor.internal_name,
        )
    else:
        image_kind = {"hero": "heroes", "item": "items", "ability": "abilities"}[
            descriptor.kind
        ]
        image_path = _catalog_image_path(image_kind, descriptor.entity_id)
    if image_path is None:
        return None
    return ProductVisualEntity(
        kind=descriptor.kind,
        imagePath=image_path,
        label=descriptor.names[0],
        names=list(descriptor.names),
    )


def _entity(
    *,
    kind: Literal["hero", "item", "ability", "team"],
    image_path: str | None,
    name_zh: str | None,
    name_en: str | None,
    aliases: list[str] | None = None,
) -> ProductVisualEntity | None:
    names = _distinct_names(name_zh, name_en, *(aliases or ()))
    if (
        not names
        or not isinstance(image_path, str)
        or not image_path.startswith(_LOCAL_ASSET_PREFIX)
    ):
        return None
    return ProductVisualEntity(kind=kind, imagePath=image_path, label=names[0], names=names)


def _catalog_image_path(
    kind: Literal["heroes", "items", "abilities"], identifier: int
) -> str | None:
    image_file = CATALOG_DIR / "images" / kind / f"{identifier}.png"
    if not image_file.is_file():
        return None
    return f"{_LOCAL_ASSET_PREFIX}dota/{kind}/{identifier}.png"


def _team_entities() -> list[ProductVisualEntity]:
    try:
        payload = json.loads(_TEAM_MANIFEST_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return []
    teams = payload.get("teams") if isinstance(payload, dict) else None
    if not isinstance(teams, list):
        return []
    entities: list[ProductVisualEntity] = []
    for team in teams:
        if not isinstance(team, dict):
            continue
        image_path = team.get("image_path")
        if not isinstance(image_path, str) or not image_path.startswith(
            f"{_LOCAL_ASSET_PREFIX}esports/teams/"
        ):
            continue
        entity = _entity(
            kind="team",
            image_path=image_path,
            name_zh=None,
            name_en=_text(team.get("name")),
            aliases=[_text(team.get("acronym")) or ""],
        )
        if entity is not None:
            entities.append(entity)
    return entities


def _distinct_names(*values: str | None) -> list[str]:
    names: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = value.strip() if isinstance(value, str) else ""
        key = normalized.casefold()
        if normalized and key not in seen:
            names.append(normalized)
            seen.add(key)
    return names


def _text(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _find_mentions(text: str, name: str, entity: ProductVisualEntity) -> list[_Mention]:
    haystack = text.casefold() if name.isascii() else text
    needle = name.casefold() if name.isascii() else name
    mentions: list[_Mention] = []
    start = 0
    while True:
        index = haystack.find(needle, start)
        if index == -1:
            return mentions
        end = index + len(name)
        if not name.isascii() or _has_ascii_token_boundary(text, index, end):
            mentions.append(_Mention(start=index, end=end, entity=entity))
        start = end


def _has_ascii_token_boundary(text: str, start: int, end: int) -> bool:
    return (start == 0 or not _ascii_word(text[start - 1])) and (
        end == len(text) or not _ascii_word(text[end])
    )


def _ascii_word(value: str) -> bool:
    return value.isascii() and (value.isalnum() or value == "_")


__all__ = ["DotaVisualEntityEnricher", "ProductVisualEntity"]
