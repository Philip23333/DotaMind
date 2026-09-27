"""Contract for resolving Valve hero and item IDs against the local snapshot."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator

CatalogKind = Literal["hero", "item"]
CatalogId = Annotated[StrictInt, Field(gt=0)]
MAX_CATALOG_LOOKUP_IDS = 20


class CatalogLookupInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: CatalogKind = Field(description="Static Dota catalog category: hero or item.")
    ids: Annotated[
        list[CatalogId],
        Field(min_length=1, max_length=MAX_CATALOG_LOOKUP_IDS),
    ] = Field(
        description=(
            "One to 20 exact Valve hero_id or item_id values. Preserve the requested IDs; "
            "do not substitute names or other identifier types."
        )
    )


class CatalogVersion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    patch: str = Field(description="Dota 2 patch represented by this committed static snapshot.")
    generated_at: datetime = Field(description="When the local snapshot was generated.")
    schema_version: int = Field(ge=1)
    source: Literal["valve_dota2_datafeed"] = "valve_dota2_datafeed"

    @field_validator("generated_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("generated_at must include a timezone")
        return value


class CatalogLookupEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: CatalogId
    status: Literal["found", "unknown"]
    name_en: str | None = Field(
        description="English static catalog label when available; not a match-provider fact."
    )
    name_zh: str | None = Field(
        description="Simplified Chinese static catalog label when available."
    )


class CatalogLookupResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: CatalogKind
    catalog_version: CatalogVersion
    entries: list[CatalogLookupEntry]


__all__ = [
    "CatalogId",
    "CatalogKind",
    "CatalogLookupEntry",
    "CatalogLookupInput",
    "CatalogLookupResult",
    "CatalogVersion",
    "MAX_CATALOG_LOOKUP_IDS",
]
