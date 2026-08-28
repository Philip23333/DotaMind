"""Deterministic local-catalog visual enrichment for product chat answers."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.integrations.valve.catalog_repository import load_default_catalog_repository

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


class DotaVisualEntityEnricher:
    """Match Final text against static local catalog and team-asset names."""

    def __init__(self) -> None:
        catalog = load_default_catalog_repository()
        entities: list[ProductVisualEntity] = []
        for hero in catalog.list_heroes():
            entity = _entity(
                kind="hero",
                image_path=f"{_LOCAL_ASSET_PREFIX}dota/heroes/{hero.hero_id}.png",
                name_zh=hero.name_zh,
                name_en=hero.name_en,
                aliases=hero.aliases,
            )
            if entity is not None:
                entities.append(entity)
        for item in catalog.list_items():
            if item.is_recipe:
                continue
            entity = _entity(
                kind="item",
                image_path=f"{_LOCAL_ASSET_PREFIX}dota/items/{item.item_id}.png",
                name_zh=item.name_zh,
                name_en=item.name_en,
                aliases=item.aliases,
            )
            if entity is not None:
                entities.append(entity)
        for ability in catalog.list_abilities():
            if ability.is_item or ability.is_talent or ability.is_innate:
                continue
            entity = _entity(
                kind="ability",
                image_path=f"{_LOCAL_ASSET_PREFIX}dota/abilities/{ability.ability_id}.png",
                name_zh=ability.name_zh,
                name_en=ability.name_en,
            )
            if entity is not None:
                entities.append(entity)
        entities.extend(_team_entities())
        self._entities = tuple(entities)

    def match(self, text: str) -> list[ProductVisualEntity]:
        """Return one local entity per longest, non-overlapping text match."""

        mentions: list[_Mention] = []
        for entity in self._entities:
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


def _entity(
    *,
    kind: Literal["hero", "item", "ability", "team"],
    image_path: str,
    name_zh: str | None,
    name_en: str | None,
    aliases: list[str] | None = None,
) -> ProductVisualEntity | None:
    names = _distinct_names(name_zh, name_en, *(aliases or ()))
    if not names or not image_path.startswith(_LOCAL_ASSET_PREFIX):
        return None
    return ProductVisualEntity(kind=kind, imagePath=image_path, label=names[0], names=names)


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
