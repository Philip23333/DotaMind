"""Resolve explicit Dota entity IDs against the injected local catalog."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr, field_validator

from app.integrations.valve.catalog_repository import (
    CatalogLookupError,
    DotaCatalogRepository,
)

EntityKind = Literal["hero", "item", "ability"]


class _ResolverModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ResolvedEntityName(_ResolverModel):
    id: StrictInt = Field(ge=0)
    status: Literal["found", "unknown"]
    name_en: StrictStr | None
    name_zh: StrictStr | None


class EntityNameCatalogVersion(_ResolverModel):
    source: Literal["valve_dota2_datafeed"]
    patch: StrictStr
    generated_at: datetime
    schema_version: StrictInt = Field(gt=0)

    @field_validator("generated_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("generated_at must include a timezone")
        return value


class EntityNameResolution(_ResolverModel):
    kind: EntityKind
    catalog_version: EntityNameCatalogVersion
    entries: list[ResolvedEntityName]


class EntityNameResolver:
    """Resolve a batch of explicit IDs without loading or caching a catalog."""

    def __init__(self, repository: DotaCatalogRepository) -> None:
        self._repository = repository

    def resolve_many(
        self,
        *,
        kind: EntityKind,
        ids: Sequence[int],
    ) -> EntityNameResolution:
        if not isinstance(kind, str) or kind not in {"hero", "item", "ability"}:
            raise ValueError("kind must be hero, item, or ability")
        if isinstance(ids, (str, bytes, bytearray)) or not isinstance(ids, Sequence):
            raise ValueError("ids must be a sequence of non-negative integers")
        if any(type(identifier) is not int or identifier < 0 for identifier in ids):
            raise ValueError("ids must be a sequence of non-negative integers")

        metadata = self._repository.snapshot_metadata()
        generated_at = datetime.fromisoformat(metadata["generated_at"])
        version = EntityNameCatalogVersion(
            source="valve_dota2_datafeed",
            patch=metadata["patch"],
            generated_at=generated_at,
            schema_version=metadata["schema_version"],
        )

        lookup = {
            "hero": self._repository.get_hero,
            "item": self._repository.get_item,
            "ability": self._repository.get_ability,
        }[kind]
        entries: list[ResolvedEntityName] = []
        seen: set[int] = set()
        for identifier in ids:
            if identifier in seen:
                continue
            seen.add(identifier)
            if identifier == 0:
                entries.append(
                    ResolvedEntityName(
                        id=identifier,
                        status="unknown",
                        name_en=None,
                        name_zh=None,
                    )
                )
                continue
            try:
                record = lookup(identifier)
            except CatalogLookupError:
                entries.append(
                    ResolvedEntityName(
                        id=identifier,
                        status="unknown",
                        name_en=None,
                        name_zh=None,
                    )
                )
                continue

            name_en = record.name_en or None
            name_zh = record.name_zh or None
            entries.append(
                ResolvedEntityName(
                    id=identifier,
                    status="found",
                    name_en=name_en,
                    name_zh=name_zh,
                )
            )

        return EntityNameResolution(kind=kind, catalog_version=version, entries=entries)
