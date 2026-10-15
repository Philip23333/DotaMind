"""Exact, local non-hero unit lookup over an independently versioned resource."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictInt,
    StrictStr,
    field_validator,
    model_validator,
)

NonHeroUnitKind = Literal[
    "lane_creep",
    "siege_creep",
    "neutral_creep",
    "tower",
    "barracks",
    "ancient",
    "building",
    "fountain",
    "courier",
    "ward",
    "roshan",
    "tormentor",
    "summoned_unit",
    "spell_unit",
    "roshans_banner",
]

_DEFAULT_MAPPING = Path(__file__).resolve().parents[2] / "data" / "units" / "unit_mapping.json"


class _UnitModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class UnitMappingSource(_UnitModel):
    repository: StrictStr = Field(min_length=1)
    revision: StrictStr = Field(pattern=r"^[0-9a-f]{40}$")
    path: StrictStr = Field(min_length=1)
    sha256: StrictStr = Field(pattern=r"^[0-9a-f]{64}$")


class UnitCatalogRecord(_UnitModel):
    internal_name: StrictStr = Field(pattern=r"^(?:npc_dota_|dota_)[a-z0-9_]+$")
    kind: NonHeroUnitKind
    name_zh: StrictStr | None
    name_en: StrictStr | None
    side: Literal["radiant", "dire"] | None = None
    lane: Literal["top", "mid", "bot"] | None = None
    tier: StrictInt | None = Field(default=None, ge=1, le=4)

    @field_validator("name_zh", "name_en")
    @classmethod
    def empty_name_is_unknown(cls, value: str | None) -> str | None:
        return value or None

    @model_validator(mode="after")
    def validate_unit_scope(self) -> UnitCatalogRecord:
        if self.internal_name.startswith("npc_dota_hero_") or self.internal_name == "dota_unknown":
            raise ValueError("Hero and source-unknown identifiers are not non-hero unit mappings")
        if self.side is not None:
            token = "goodguys" if self.side == "radiant" else "badguys"
            prefixes = (f"npc_dota_{token}_", f"npc_dota_creep_{token}_")
            if not self.internal_name.startswith(prefixes):
                raise ValueError("Unit side requires an explicit matching side in its identifier")
        if self.tier is not None:
            pattern = rf"npc_dota_(?:goodguys|badguys)_tower{self.tier}(?:_(?:top|mid|bot))?"
            if self.kind != "tower" or re.fullmatch(pattern, self.internal_name) is None:
                raise ValueError("Tower tier must match its explicit unit identifier")
        if self.lane is not None:
            if self.kind not in {"tower", "barracks"} or not self.internal_name.endswith(
                f"_{self.lane}"
            ):
                raise ValueError("Building lane must match its explicit unit identifier")
        return self


class UnitMappingSnapshot(_UnitModel):
    schema_version: StrictInt = Field(ge=1, le=1)
    sources: tuple[UnitMappingSource, ...] = Field(min_length=1)
    units: tuple[UnitCatalogRecord, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_unit_names(self) -> UnitMappingSnapshot:
        names = [record.internal_name for record in self.units]
        if len(names) != len(set(names)):
            raise ValueError("Duplicate unit identifiers in mapping resource")
        return self


class UnitCatalog:
    """Pin one validated snapshot; lookups do no I/O or name normalization."""

    def __init__(self, snapshot: UnitMappingSnapshot) -> None:
        self._units = {record.internal_name: record for record in snapshot.units}
        self._sources = snapshot.sources
        canonical = json.dumps(
            snapshot.model_dump(mode="json"),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        self._version = f"sha256:{hashlib.sha256(canonical).hexdigest()}"

    @classmethod
    def from_file(cls, path: Path) -> UnitCatalog:
        # Resource errors are not per-key misses and must propagate to the caller.
        snapshot = UnitMappingSnapshot.model_validate_json(path.read_bytes())
        return cls(snapshot)

    @classmethod
    def load_default(cls) -> UnitCatalog:
        return cls.from_file(_DEFAULT_MAPPING)

    @property
    def version(self) -> str:
        return self._version

    @property
    def sources(self) -> tuple[UnitMappingSource, ...]:
        return self._sources

    def lookup(self, internal_name: str) -> UnitCatalogRecord | None:
        if not isinstance(internal_name, str) or not internal_name:
            raise ValueError("Unit identifier must be a non-empty string")
        return self._units.get(internal_name)
