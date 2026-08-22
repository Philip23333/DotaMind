"""Read-only runtime access to committed Valve catalog snapshots."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from functools import lru_cache
from pathlib import Path
from typing import Any, Generic, Literal, TypeVar

from app.integrations.valve.catalog import (
    AbilityCatalogRecord,
    CatalogManifest,
    CatalogValidationError,
    HeroCatalogRecord,
    ItemCatalogRecord,
    RecipeEdge,
    TalentTier,
    validate_catalog,
)

CATALOG_DIR = Path(__file__).resolve().parents[2] / "data" / "catalog"
CATALOG_IMAGE_BASE_PATH = "/api/v1/assets/dota"
ResolutionStatus = Literal["resolved", "ambiguous", "not_found"]
NON_STANDARD_UPGRADE_TARGET_INTERNAL_NAMES = frozenset({"item_trident"})


class CatalogSnapshotError(RuntimeError):
    """Raised when committed catalog files are missing or invalid."""


class CatalogLookupError(LookupError):
    """Raised when an ID lookup is not present in the loaded snapshot."""


@dataclass(frozen=True)
class _Entity:
    identifier: int
    internal_name: str
    name_en: str
    name_zh: str
    aliases: tuple[str, ...]
    is_recipe: bool = False


EntityModel = TypeVar("EntityModel", HeroCatalogRecord, ItemCatalogRecord)


class _Resolver(Generic[EntityModel]):
    def __init__(
        self,
        records: list[EntityModel],
        *,
        entity: Literal["hero", "item"],
        fuzzy_score_cutoff: float = 0.72,
        ambiguity_score_delta: float = 0.04,
        candidate_limit: int = 5,
    ) -> None:
        self.entity = entity
        self.fuzzy_score_cutoff = fuzzy_score_cutoff
        self.ambiguity_score_delta = ambiguity_score_delta
        self.candidate_limit = candidate_limit
        self._records = records
        self._entities = [self._entity(record) for record in records]
        self._index = self._build_index(self._entities)

    def resolve(self, query: str) -> dict[str, Any]:
        normalized = normalize_catalog_key(query)
        if not normalized:
            return self._not_found(query)

        entities = self._index.get(normalized, [])
        if self.entity == "item":
            entities = self._prefer_recipe_scope(normalized, entities)
        if len(entities) == 1:
            return self._resolved(query, entities[0], method="exact")
        if len(entities) > 1:
            return self._ambiguous(query, entities, method="exact_alias")

        fuzzy = self._fuzzy_candidates(normalized)
        if not fuzzy:
            return self._not_found(query)
        best_score = fuzzy[0][1]
        close = [
            entity
            for entity, score in fuzzy
            if best_score - score <= self.ambiguity_score_delta
        ]
        if len(close) == 1:
            return self._resolved(query, close[0], method="fuzzy", score=best_score)
        return self._ambiguous(query, close, method="fuzzy", score=best_score)

    def _fuzzy_candidates(self, normalized: str) -> list[tuple[_Entity, float]]:
        scoped_entities = self._entities
        if self.entity == "item":
            scoped_entities = self._item_scope(normalized)
        scored_by_id: dict[int, tuple[_Entity, float]] = {}
        for key, entities in self._index.items():
            score = SequenceMatcher(None, normalized, key).ratio()
            if score < self.fuzzy_score_cutoff:
                continue
            for entity in entities:
                if entity not in scoped_entities:
                    continue
                current = scored_by_id.get(entity.identifier)
                if current is None or score > current[1]:
                    scored_by_id[entity.identifier] = (entity, score)
        return sorted(
            scored_by_id.values(),
            key=lambda item: (item[1], item[0].is_recipe, item[0].name_zh, item[0].identifier),
            reverse=True,
        )[: self.candidate_limit]

    def _prefer_recipe_scope(self, normalized: str, entities: list[_Entity]) -> list[_Entity]:
        scoped = self._item_scope(normalized)
        scoped_ids = {entity.identifier for entity in scoped}
        return [entity for entity in entities if entity.identifier in scoped_ids]

    def _item_scope(self, normalized: str) -> list[_Entity]:
        asks_recipe = any(token in normalized for token in ("recipe", "图纸", "配方"))
        if asks_recipe:
            return [entity for entity in self._entities if entity.is_recipe]
        final_items = [entity for entity in self._entities if not entity.is_recipe]
        return final_items or self._entities

    def _entity(self, record: EntityModel) -> _Entity:
        if isinstance(record, HeroCatalogRecord):
            return _Entity(
                identifier=record.hero_id,
                internal_name=record.internal_name,
                name_en=record.name_en,
                name_zh=record.name_zh,
                aliases=tuple(record.aliases),
            )
        return _Entity(
            identifier=record.item_id,
            internal_name=record.internal_name,
            name_en=record.name_en,
            name_zh=record.name_zh,
            aliases=tuple(record.aliases),
            is_recipe=record.is_recipe,
        )

    def _build_index(self, entities: list[_Entity]) -> dict[str, list[_Entity]]:
        index: dict[str, list[_Entity]] = {}
        for entity in entities:
            prefix = "npc_dota_hero_" if self.entity == "hero" else "item_"
            keys = [entity.name_en, entity.name_zh, *entity.aliases]
            keys.append(entity.internal_name.removeprefix(prefix))
            if self.entity == "item":
                keys.append(entity.internal_name.removeprefix("item_recipe_"))
            for key in keys:
                normalized = normalize_catalog_key(key)
                if not normalized:
                    continue
                bucket = index.setdefault(normalized, [])
                if all(existing.identifier != entity.identifier for existing in bucket):
                    bucket.append(entity)
        return index

    def _resolved(
        self,
        query: str,
        entity: _Entity,
        *,
        method: str,
        score: float | None = None,
    ) -> dict[str, Any]:
        payload = self._serialize(entity)
        return {
            "status": "resolved",
            "query": query,
            self.entity: payload,
            "candidates": [payload],
            "method": method,
            "score": score,
        }

    def _ambiguous(
        self,
        query: str,
        entities: list[_Entity],
        *,
        method: str,
        score: float | None = None,
    ) -> dict[str, Any]:
        return {
            "status": "ambiguous",
            "query": query,
            self.entity: None,
            "candidates": [self._serialize(entity) for entity in entities[: self.candidate_limit]],
            "method": method,
            "score": score,
        }

    def _not_found(self, query: str) -> dict[str, Any]:
        return {
            "status": "not_found",
            "query": query,
            self.entity: None,
            "candidates": [],
            "method": "none",
            "score": None,
        }

    def _serialize(self, entity: _Entity) -> dict[str, Any]:
        if self.entity == "hero":
            return {
                "hero_id": entity.identifier,
                "name": entity.internal_name,
                "name_en": entity.name_en,
                "name_zh": entity.name_zh,
                "localized_name": entity.name_zh or entity.name_en,
                "aliases": list(entity.aliases),
                "image_path": f"{CATALOG_IMAGE_BASE_PATH}/heroes/{entity.identifier}.png",
            }
        return {
            "item_id": entity.identifier,
            "name": entity.internal_name,
            "name_en": entity.name_en,
            "name_zh": entity.name_zh,
            "localized_name": entity.name_zh or entity.name_en,
            "aliases": list(entity.aliases),
            "is_recipe": entity.is_recipe,
            "image_path": (
                None
                if entity.is_recipe
                else f"{CATALOG_IMAGE_BASE_PATH}/items/{entity.identifier}.png"
            ),
        }


class DotaCatalogRepository:
    """Immutable-in-practice repository loaded once from committed snapshots."""

    def __init__(self, snapshot_dir: Path | None = None) -> None:
        directory = (snapshot_dir or CATALOG_DIR).resolve()
        self.snapshot_dir = directory
        self.manifest = _load_model(directory / "manifest.json", CatalogManifest)
        heroes = _load_list(directory / "dota2_heroes.json", HeroCatalogRecord)
        abilities = _load_list(directory / "dota2_abilities.json", AbilityCatalogRecord)
        item_payload = _load_json(directory / "dota2_items.json")
        if isinstance(item_payload, list):
            item_records = item_payload
            recipe_payload: list[dict[str, Any]] = []
        elif isinstance(item_payload, dict):
            item_records = item_payload.get("items")
            recipe_payload = item_payload.get("recipes", [])
        else:
            item_records = None
            recipe_payload = []
        if not isinstance(item_records, list) or not isinstance(recipe_payload, list):
            raise CatalogSnapshotError("dota2_items.json must contain items and recipes lists")
        try:
            items = [ItemCatalogRecord.model_validate(item) for item in item_records]
            recipes = [RecipeEdge.model_validate(item) for item in recipe_payload]
        except ValueError as exc:
            raise CatalogSnapshotError("invalid catalog schema: dota2_items.json") from exc
        try:
            validate_catalog(self.manifest, heroes, abilities, items)
        except (CatalogValidationError, ValueError) as exc:
            raise CatalogSnapshotError(f"invalid Dota catalog snapshot: {exc}") from exc

        self._heroes = {record.hero_id: record for record in heroes}
        self._abilities = {record.ability_id: record for record in abilities}
        self._items = {record.item_id: record for record in items}
        self._recipes = tuple(recipes)
        self._item_ids_with_purchasable_upgrades = frozenset(
            component_item_id
            for edge in recipes
            if any(
                (upgrade_item := self._items.get(upgrade_item_id)) is not None
                and upgrade_item.is_purchasable
                and upgrade_item.internal_name
                not in NON_STANDARD_UPGRADE_TARGET_INTERNAL_NAMES
                for upgrade_item_id in edge.upgrade_item_ids
            )
            for component_item_id in edge.component_item_ids
        )
        recipe_edges_by_item_id: dict[int, list[RecipeEdge]] = {}
        for edge in recipes:
            related_ids = (edge.recipe_item_id, *edge.upgrade_item_ids)
            for item_id in related_ids:
                bucket = recipe_edges_by_item_id.setdefault(item_id, [])
                if all(existing.recipe_item_id != edge.recipe_item_id for existing in bucket):
                    bucket.append(edge)
        self._recipe_edges_by_item_id = {
            item_id: tuple(edges) for item_id, edges in recipe_edges_by_item_id.items()
        }
        self._hero_resolver = _Resolver(heroes, entity="hero")
        self._item_resolver = _Resolver(items, entity="item")

    @classmethod
    def load_default(cls) -> DotaCatalogRepository:
        return cls()

    def get_hero(self, hero_id: int) -> HeroCatalogRecord:
        return self._copy_or_raise(self._heroes, hero_id, "hero")

    def list_heroes(self) -> list[HeroCatalogRecord]:
        return [record.model_copy(deep=True) for record in self._heroes.values()]

    def hero_name_index(self) -> dict[int, str]:
        return {hero_id: record.name_en for hero_id, record in self._heroes.items()}

    def list_items(self) -> list[ItemCatalogRecord]:
        return [record.model_copy(deep=True) for record in self._items.values()]

    def get_ability(self, ability_id: int) -> AbilityCatalogRecord:
        return self._copy_or_raise(self._abilities, ability_id, "ability")

    def get_item(self, item_id: int) -> ItemCatalogRecord:
        return self._copy_or_raise(self._items, item_id, "item")

    def get_item_by_internal_name(self, name: str) -> ItemCatalogRecord:
        """Return an item by exact internal name, accepting ``item_`` variants."""

        normalized = normalize_catalog_key(name)
        if not normalized:
            raise CatalogLookupError(f"item not found: {name}")
        candidates = {normalized}
        if normalized.startswith("item "):
            candidates.add(normalized.removeprefix("item "))
        else:
            candidates.add(f"item {normalized}")
        for record in self._items.values():
            internal_name = normalize_catalog_key(record.internal_name)
            if internal_name in candidates:
                return record.model_copy(deep=True)
        raise CatalogLookupError(f"item not found: {name}")

    def get_item_recipe_edges(self, item_id: int) -> list[RecipeEdge]:
        """Return recipe edges for a recipe scroll or one of its finished items."""

        self.get_item(item_id)
        return [
            edge.model_copy(deep=True)
            for edge in self._recipe_edges_by_item_id.get(int(item_id), ())
        ]

    def is_terminal_item(self, item_id: int) -> bool:
        """Whether an item has no current purchasable upgrade target."""

        item = self.get_item(item_id)
        return not item.is_recipe and item.item_id not in self._item_ids_with_purchasable_upgrades

    def get_hero_abilities(self, hero_id: int) -> list[AbilityCatalogRecord]:
        hero = self.get_hero(hero_id)
        return [self.get_ability(ability_id) for ability_id in hero.ability_ids]

    def get_hero_talent_tree(self, hero_id: int) -> list[TalentTier]:
        hero = self.get_hero(hero_id)
        tree: list[TalentTier] = []
        for tier in hero.talent_tiers:
            self.get_ability(tier.left_ability_id)
            self.get_ability(tier.right_ability_id)
            tree.append(tier.model_copy(deep=True))
        return tree

    def resolve_hero(self, query: str) -> dict[str, Any]:
        return self._hero_resolver.resolve(query)

    def resolve_item(self, query: str) -> dict[str, Any]:
        return self._item_resolver.resolve(query)

    def snapshot_metadata(self) -> dict[str, Any]:
        return {
            "patch": self.manifest.patch,
            "generated_at": self.manifest.generated_at.isoformat(),
            "schema_version": self.manifest.schema_version,
            "game": self.manifest.game,
            "locales": list(self.manifest.locales),
            "source": "Valve Dota 2 Datafeed snapshot",
            "status": "committed_snapshot",
        }

    @staticmethod
    def _copy_or_raise(
        records: dict[int, EntityModel], identifier: int, entity: str
    ) -> EntityModel:
        try:
            record = records[int(identifier)]
        except (KeyError, TypeError, ValueError) as exc:
            raise CatalogLookupError(f"{entity} not found: {identifier}") from exc
        return record.model_copy(deep=True)


@lru_cache(maxsize=1)
def load_default_catalog_repository() -> DotaCatalogRepository:
    """Load the default committed snapshot once per process."""

    return DotaCatalogRepository.load_default()


def normalize_catalog_key(value: str) -> str:
    lowered = str(value).strip().lower().replace("'", "")
    lowered = lowered.replace("-", " ").replace("_", " ")
    return re.sub(r"\s+", " ", lowered).strip()


def _load_json(path: Path) -> Any:
    if not path.is_file():
        raise CatalogSnapshotError(f"catalog file missing: {path.name}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CatalogSnapshotError(f"catalog file unreadable: {path.name}") from exc


def _load_model(path: Path, model: type[EntityModel]) -> EntityModel:
    try:
        return model.model_validate(_load_json(path))
    except CatalogSnapshotError:
        raise
    except ValueError as exc:
        raise CatalogSnapshotError(f"invalid catalog schema: {path.name}") from exc


def _load_list(path: Path, model: type[EntityModel]) -> list[EntityModel]:
    payload = _load_json(path)
    if not isinstance(payload, list):
        raise CatalogSnapshotError(f"catalog file must contain a JSON list: {path.name}")
    try:
        return [model.model_validate(item) for item in payload]
    except ValueError as exc:
        raise CatalogSnapshotError(f"invalid catalog schema: {path.name}") from exc
