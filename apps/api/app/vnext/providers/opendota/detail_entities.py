"""Local entity enrichment at explicit OpenDota fields, without fuzzy resolution."""

from __future__ import annotations

from typing import Any, Literal

from app.integrations.valve.catalog_repository import DotaCatalogRepository
from app.vnext.capabilities.game.data import CoverageData, EntityData
from app.vnext.catalog import EntityKind, EntityNameResolver

from .detail_values import ABSENT, _missing


class DetailEntities:
    def __init__(self, catalog: DotaCatalogRepository) -> None:
        self._resolver = EntityNameResolver(catalog)
        self.catalog_version = self._resolver.resolve_many(kind="hero", ids=[]).catalog_version
        self.hero_ids = self._index(catalog.list_heroes(), "hero_id")
        self._item_ids = self._index(catalog.list_items(), "item_id")
        self._cache = {}

    @staticmethod
    def _index(records, id_field: str) -> dict[str, int]:
        result = {}
        for row in records:
            if row.internal_name in result:
                raise ValueError("Catalog internal names must be unique")
            result[row.internal_name] = getattr(row, id_field)
        return result

    def by_id(
        self, value: Any, kind: EntityKind, path: str, source_path: str,
        coverage: CoverageData, *, empty_zero: bool = False, required: bool = True,
        source_value: Any = ABSENT,
    ) -> EntityData | None:
        evidence = value if source_value is ABSENT else source_value
        if value is ABSENT or value is None:
            if required:
                _missing(coverage, path, "Source entity ID unavailable", source_path=source_path,
                         source_value=evidence)
            return None
        if type(value) is not int or value < 0:
            _missing(coverage, path, "Source entity ID invalid", source_path=source_path,
                     source_value=evidence)
            return None
        if value == 0 and empty_zero:
            return None
        key = (kind, value)
        if key not in self._cache:
            batch = self._resolver.resolve_many(kind=kind, ids=[value])
            if batch.catalog_version != self.catalog_version:
                raise ValueError("Catalog version changed within one detail projection")
            self._cache[key] = batch.entries[0]
        name = self._cache[key]
        if name.status == "unknown":
            _missing(coverage, path, "Catalog ID not found", source_path=source_path,
                     source_value=evidence)
        else:
            for language in ("name_zh", "name_en"):
                if getattr(name, language) is None:
                    _missing(coverage, f"{path}.{language}", "Catalog localized name unavailable",
                             source_path=source_path, source_value=evidence)
        return EntityData(id=value, name_zh=name.name_zh, name_en=name.name_en)

    def by_key(
        self, value: Any, kind: Literal["hero", "item"], path: str, source_path: str,
        coverage: CoverageData, *, required: bool = True,
    ) -> EntityData | None:
        if (value is ABSENT or value is None) and not required:
            return None
        index = self.hero_ids if kind == "hero" else self._item_ids
        key = value if kind == "hero" else f"item_{value}"
        identifier = index.get(key) if type(value) is str else None
        if identifier is None:
            _missing(coverage, path, "Catalog key not found", source_path=source_path,
                     source_value=value)
            return None
        return self.by_id(identifier, kind, path, source_path, coverage, source_value=value)
