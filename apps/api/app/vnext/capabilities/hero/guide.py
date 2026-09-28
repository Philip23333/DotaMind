"""Pydantic contracts for hero guide queries and source-backed observations."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    FiniteFloat,
    JsonValue,
    StrictBool,
    StrictInt,
    field_validator,
    model_validator,
)

from app.vnext.catalog import EntityNameCatalogVersion, ResolvedEntityName

HeroPosition = Annotated[StrictInt, Field(ge=1, le=5)]
GuideSection = Literal["all", "items", "skills", "pro_examples"]

_PositiveInt = Annotated[StrictInt, Field(gt=0)]
_NonNegativeInt = Annotated[StrictInt, Field(ge=0)]
_Steam32AccountId = Annotated[StrictInt, Field(ge=0, le=4_294_967_295)]
_JsonObject = dict[str, JsonValue]


class HeroGuideInput(BaseModel):
    """Select one hero and lane-position guide view."""

    model_config = ConfigDict(extra="forbid")

    hero_id: _PositiveInt
    position: HeroPosition
    section: GuideSection = "all"


class GuideSourceMetadata(BaseModel):
    """Independent availability and provenance state for one D2PT partition."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    provider: Literal["d2pt"]
    sample_type: Literal["pub", "pro"]
    availability: Literal["available", "empty", "missing"]
    stale: bool
    retrieved_at: datetime | None = None
    source_updated_at: str | None = None
    last_attempt_at: datetime | None = None
    last_error: str | None = None
    scope: _JsonObject = Field(default_factory=dict)

    @field_validator("retrieved_at", "last_attempt_at")
    @classmethod
    def require_timezone_when_present(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("timestamps must include a timezone")
        return value


class GuideItem(BaseModel):
    """One item occurrence in a Pub guide observation."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    item_id: _PositiveInt
    quantity: _PositiveInt
    name: str | None
    resolved_name: ResolvedEntityName | None = None


class StartingItemOption(BaseModel):
    """One independently sourced starting-item option and its raw statistics."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    items: list[GuideItem] = Field(default_factory=list)
    statistics: _JsonObject = Field(default_factory=dict)
    source_path: str


class ItemTiming(BaseModel):
    """A source-attributed average or median item timing, when supplied."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    kind: Literal["median", "average"]
    minute: FiniteFloat
    source_path: str


class GuideItemObservation(BaseModel):
    """An item candidate with unmodified source statistics and location."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    item_id: _PositiveInt
    name: str | None = None
    phase: Literal["mid", "late", "unknown"]
    timing: ItemTiming | None = None
    statistics: _JsonObject = Field(default_factory=dict)
    source_path: str
    resolved_name: ResolvedEntityName | None = None


class SkillSequenceOption(BaseModel):
    """One ordered source skill sequence; no hero-level expansion is implied."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    ability_ids: list[_PositiveInt] = Field(default_factory=list)
    abilities: list[ResolvedEntityName] = Field(default_factory=list)
    statistics: _JsonObject = Field(default_factory=dict)
    source_path: str


class TalentObservation(BaseModel):
    """One talent observation with source-specific detail kept intact."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    level: _PositiveInt | None = None
    data: _JsonObject = Field(default_factory=dict)
    source_path: str


class PubGuide(BaseModel):
    """A Pub build projection whose item and skill candidates remain unpaired."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    build_id: _NonNegativeInt | None = None
    facet_id: _NonNegativeInt | None = None
    source_updated_at: str | None = None
    scope: _JsonObject = Field(default_factory=dict)
    statistics: _JsonObject = Field(default_factory=dict)
    starting_options: list[StartingItemOption] = Field(default_factory=list)
    item_progression: list[GuideItemObservation] = Field(default_factory=list)
    situational_items: list[GuideItemObservation] = Field(default_factory=list)
    skill_sequences: list[SkillSequenceOption] = Field(default_factory=list)
    talents: list[TalentObservation] = Field(default_factory=list)


class ProItemEvent(BaseModel):
    """One ordered item event from a professional-match example."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    item_id: _PositiveInt
    minute: FiniteFloat | None = None
    source_fields: _JsonObject = Field(default_factory=dict)
    resolved_name: ResolvedEntityName | None = None


class ProAbilityEvent(BaseModel):
    """One ordered ability-level event from a professional-match example.

    Source ability IDs, including zero, are retained. Zero is not mapped to a
    named ability or interpreted as a specific kind of level-up event.
    """

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    ability_id: _NonNegativeInt
    time_seconds: FiniteFloat | None = None
    hero_level: _PositiveInt | None = None
    source_fields: _JsonObject = Field(default_factory=dict)
    resolved_name: ResolvedEntityName | None = None


class ProMatchExample(BaseModel):
    """A concrete Pro recent-match example without an inferred Pub-build link."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    source_match_id: _PositiveInt
    account_id: _Steam32AccountId | None = None
    hero_id: _PositiveInt
    position: HeroPosition | None = None
    position_basis: Literal["draft", "build", "unknown"]
    date: str | None = None
    started_at_unix: _NonNegativeInt | None = None
    player_name: str | None = None
    team_name: str | None = None
    opponent_name: str | None = None
    won: StrictBool | None = None
    duration_seconds: _NonNegativeInt | None = None
    item_timeline: list[ProItemEvent] = Field(default_factory=list)
    ability_timeline: list[ProAbilityEvent] = Field(default_factory=list)
    talent_choices: list[_JsonObject] = Field(default_factory=list)
    source_path: str


class HeroGuideResult(BaseModel):
    """Combined Pub guide and Pro example query view with independent source state."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    hero_id: _PositiveInt
    position: HeroPosition
    section: GuideSection
    pub_metadata: GuideSourceMetadata
    pro_metadata: GuideSourceMetadata
    pub_guides: list[PubGuide] = Field(default_factory=list)
    pro_examples: list[ProMatchExample] = Field(default_factory=list)
    pub_guides_total: _NonNegativeInt | None = None
    pro_examples_total: _NonNegativeInt | None = None
    hero_name: ResolvedEntityName | None = None
    catalog_version: EntityNameCatalogVersion | None = None

    @model_validator(mode="after")
    def validate_source_metadata_kinds(self) -> HeroGuideResult:
        if self.pub_metadata.sample_type != "pub":
            raise ValueError("pub_metadata.sample_type must be 'pub'")
        if self.pro_metadata.sample_type != "pro":
            raise ValueError("pro_metadata.sample_type must be 'pro'")
        return self
