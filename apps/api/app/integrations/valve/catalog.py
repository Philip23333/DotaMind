"""Normalized, bilingual Valve catalog models and sync-time validation.

This module intentionally contains no HTTP code.  The offline sync script
passes decoded Datafeed records to the functions below, which clean display
text, resolve value placeholders, and fail before any snapshot is written when
relationships are not closed.
"""

from __future__ import annotations

import html
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class CatalogValidationError(ValueError):
    """Raised when Valve records cannot form a closed catalog snapshot."""


@dataclass(frozen=True)
class TalentBonusCandidate:
    source_ability_id: int
    source_internal_name: str
    field_name: str
    value: Any
    operation: int


TalentBonusIndex = dict[tuple[str, str], tuple[TalentBonusCandidate, ...]]


class CatalogModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CatalogManifest(CatalogModel):
    schema_version: int = Field(default=1, ge=1)
    game: str = "dota2"
    patch: str = Field(min_length=1)
    generated_at: datetime
    locales: list[str] = Field(min_length=2)
    sources: list[str] = Field(min_length=1)
    entity_counts: dict[str, int]

    @field_validator("locales")
    @classmethod
    def require_catalog_locales(cls, value: list[str]) -> list[str]:
        if value != ["english", "schinese"]:
            raise ValueError("catalog locales must be ['english', 'schinese']")
        return value

    @field_validator("entity_counts")
    @classmethod
    def require_nonnegative_counts(cls, value: dict[str, int]) -> dict[str, int]:
        if any(count < 0 for count in value.values()):
            raise ValueError("catalog entity counts cannot be negative")
        return value


class SpecialBonus(CatalogModel):
    talent_internal_name: str = Field(min_length=1)
    value: Any
    operation: int = 0


class SpecialValue(CatalogModel):
    name: str = Field(min_length=1)
    values: list[Any] = Field(default_factory=list)
    is_percentage: bool = False
    heading_en: str = ""
    heading_zh: str = ""
    bonuses: list[SpecialBonus] = Field(default_factory=list)
    rendered_en: str = ""
    rendered_zh: str = ""


class TalentTier(CatalogModel):
    level: int
    left_ability_id: int = Field(gt=0)
    right_ability_id: int = Field(gt=0)

    @field_validator("level")
    @classmethod
    def require_talent_level(cls, value: int) -> int:
        if value not in {10, 15, 20, 25}:
            raise ValueError("talent level must be one of 10, 15, 20, 25")
        return value


class AbilityCatalogRecord(CatalogModel):
    ability_id: int = Field(gt=0)
    internal_name: str = Field(min_length=1)
    name_en: str = ""
    name_zh: str = ""
    description_en: str = ""
    description_zh: str = ""
    lore_en: str = ""
    lore_zh: str = ""
    notes_en: list[str] = Field(default_factory=list)
    notes_zh: list[str] = Field(default_factory=list)
    scepter_en: str = ""
    scepter_zh: str = ""
    shard_en: str = ""
    shard_zh: str = ""
    behavior: str = ""
    target_team: Any = None
    target_type: Any = None
    flags: Any = None
    damage: Any = None
    immunity: Any = None
    dispellable: Any = None
    max_level: int = 0
    cast_ranges: list[Any] = Field(default_factory=list)
    cast_points: list[Any] = Field(default_factory=list)
    channel_times: list[Any] = Field(default_factory=list)
    cooldowns: list[Any] = Field(default_factory=list)
    durations: list[Any] = Field(default_factory=list)
    damages: list[Any] = Field(default_factory=list)
    mana_costs: list[Any] = Field(default_factory=list)
    gold_costs: list[Any] = Field(default_factory=list)
    health_costs: list[Any] = Field(default_factory=list)
    special_values: list[SpecialValue] = Field(default_factory=list)
    is_item: bool = False
    is_innate: bool = False
    has_scepter: bool = False
    has_shard: bool = False
    granted_by_scepter: bool = False
    granted_by_shard: bool = False
    is_talent: bool = False
    hero_ids: list[int] = Field(default_factory=list)


class HeroCatalogRecord(CatalogModel):
    hero_id: int = Field(gt=0)
    internal_name: str = Field(min_length=1)
    name_en: str = ""
    name_zh: str = ""
    aliases: list[str] = Field(default_factory=list)
    primary_attribute: Any = None
    complexity: Any = None
    attack_capability: Any = None
    role_levels: list[Any] = Field(default_factory=list)
    strength_base: Any = None
    strength_gain: Any = None
    agility_base: Any = None
    agility_gain: Any = None
    intelligence_base: Any = None
    intelligence_gain: Any = None
    damage_min: Any = None
    damage_max: Any = None
    attack_rate: Any = None
    attack_range: Any = None
    projectile_speed: Any = None
    armor: Any = None
    magic_resistance: Any = None
    movement_speed: Any = None
    turn_rate: Any = None
    sight_range_day: Any = None
    sight_range_night: Any = None
    max_health: Any = None
    health_regen: Any = None
    max_mana: Any = None
    mana_regen: Any = None
    ability_ids: list[int] = Field(default_factory=list)
    talent_tiers: list[TalentTier] = Field(min_length=4, max_length=4)

    @model_validator(mode="after")
    def require_all_talent_levels(self) -> HeroCatalogRecord:
        levels = [tier.level for tier in self.talent_tiers]
        if levels != [10, 15, 20, 25]:
            raise ValueError("hero talent tiers must be ordered 10, 15, 20, 25")
        return self


class RecipeEdge(CatalogModel):
    recipe_item_id: int = Field(gt=0)
    component_item_ids: list[int] = Field(min_length=1)
    upgrade_item_ids: list[int] = Field(min_length=1)


class ItemCatalogRecord(CatalogModel):
    item_id: int = Field(gt=0)
    internal_name: str = Field(min_length=1)
    name_en: str = ""
    name_zh: str = ""
    aliases: list[str] = Field(default_factory=list)
    description_en: str = ""
    description_zh: str = ""
    lore_en: str = ""
    lore_zh: str = ""
    notes_en: list[str] = Field(default_factory=list)
    notes_zh: list[str] = Field(default_factory=list)
    scepter_en: str = ""
    scepter_zh: str = ""
    shard_en: str = ""
    shard_zh: str = ""
    price: Any = None
    quality: Any = None
    stock: Any = None
    initial_charges: Any = None
    neutral_tier: Any = None
    behavior: str = ""
    target_team: Any = None
    target_type: Any = None
    cooldowns: list[Any] = Field(default_factory=list)
    durations: list[Any] = Field(default_factory=list)
    mana_costs: list[Any] = Field(default_factory=list)
    health_costs: list[Any] = Field(default_factory=list)
    special_values: list[SpecialValue] = Field(default_factory=list)
    recipe_component_ids: list[int] = Field(default_factory=list)
    upgrade_item_ids: list[int] = Field(default_factory=list)
    is_recipe: bool = False
    is_neutral: bool = False
    is_purchasable: bool = False


class CatalogExcludedEntity(CatalogModel):
    entity_type: Literal["hero", "ability", "item"]
    entity_id: int = Field(gt=0)
    internal_name: str = Field(min_length=1)
    classification: Literal["legacy_or_unclassified"] = "legacy_or_unclassified"
    reason: str = Field(min_length=1)
    raw_description_en: str
    raw_description_zh: str
    unresolved_tokens_en: list[str]
    unresolved_tokens_zh: list[str]
    official_status_evidence: dict[str, Any]


class CatalogSyncAudit(CatalogModel):
    schema_version: int = Field(default=1, ge=1)
    patch: str = Field(min_length=1)
    generated_at: datetime
    excluded_entities: list[CatalogExcludedEntity] = Field(default_factory=list)


class CatalogBundle(CatalogModel):
    manifest: CatalogManifest
    heroes: list[HeroCatalogRecord]
    abilities: list[AbilityCatalogRecord]
    items: list[ItemCatalogRecord]
    recipes: list[RecipeEdge] = Field(default_factory=list)
    sync_audit: CatalogSyncAudit | None = None


_TOKEN_RE = re.compile(r"%([A-Za-z0-9_]+)%|\{s:([A-Za-z0-9_]+)\}")
_HTML_BREAK_RE = re.compile(r"<br\s*/?>", flags=re.IGNORECASE)
_HTML_HEADING_RE = re.compile(r"</?h[1-6]>", flags=re.IGNORECASE)
_HTML_TAG_RE = re.compile(r"<[^>]+>")


def clean_text(value: Any) -> str:
    """Convert Valve's small HTML subset into stable plain text."""

    if value is None:
        return ""
    text = html.unescape(str(value)).replace("\r\n", "\n").replace("\r", "\n")
    text = _HTML_BREAK_RE.sub("\n", text)
    text = _HTML_HEADING_RE.sub("\n", text)
    text = _HTML_TAG_RE.sub("", text)
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.split("\n")]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def extract_display_tokens(value: Any) -> list[str]:
    """Return normalized Valve display-token names in deterministic order."""

    text = str(value or "")
    return sorted(
        {
            match.group(1) or match.group(2) or ""
            for match in _TOKEN_RE.finditer(text)
            if match.group(1) or match.group(2)
        }
    )


def normalize_ability(
    english: Mapping[str, Any],
    chinese: Mapping[str, Any],
    *,
    hero_ids: Iterable[int] = (),
    is_talent: bool = False,
    talent_bonuses: Mapping[str, Mapping[str, Any]] | None = None,
) -> AbilityCatalogRecord:
    _assert_bilingual_identity(english, chinese, "ability")
    notes_en, notes_zh = _localized_ability_notes(english, chinese)
    has_scepter = bool(english.get("ability_has_scepter"))
    has_shard = bool(english.get("ability_has_shard"))
    own_values = _value_map(english.get("special_values", []))
    own_values = _apply_ability_base_replacement_exceptions(english, own_values)
    scepter_values = (
        _value_map(english.get("special_values", []), upgrade_key="values_scepter")
        if has_scepter
        else {}
    )
    shard_values = (
        _value_map(english.get("special_values", []), upgrade_key="values_shard")
        if has_shard
        else {}
    )
    current_talent_bonuses = {}
    if is_talent:
        talent_name = str(english.get("name") or "")
        current_talent_bonuses = {
            talent_name: (talent_bonuses or {}).get(talent_name, {})
        }
    bonus_values = _flatten_talent_bonuses(current_talent_bonuses)
    # Current ability/talent values take precedence over the cross-ability
    # talent bonus index, matching the sync contract's resolution order.
    replacements = {**bonus_values, **own_values}
    scepter_replacements = {**bonus_values, **scepter_values}
    shard_replacements = {**bonus_values, **shard_values}
    specials = _normalize_special_values(
        english.get("special_values", []), chinese.get("special_values", []), replacements
    )
    return AbilityCatalogRecord(
        ability_id=int(english["id"]),
        internal_name=str(english["name"]),
        name_en=_render(english.get("name_loc"), replacements),
        name_zh=_render(chinese.get("name_loc"), replacements),
        description_en=_render(english.get("desc_loc"), replacements),
        description_zh=_render(chinese.get("desc_loc"), replacements),
        lore_en=_render(english.get("lore_loc"), replacements),
        lore_zh=_render(chinese.get("lore_loc"), replacements),
        notes_en=[_render(item, replacements) for item in notes_en],
        notes_zh=[_render(item, replacements) for item in notes_zh],
        scepter_en=(
            _render(english.get("scepter_loc"), scepter_replacements) if has_scepter else ""
        ),
        scepter_zh=(
            _render(chinese.get("scepter_loc"), scepter_replacements) if has_scepter else ""
        ),
        shard_en=_render(english.get("shard_loc"), shard_replacements) if has_shard else "",
        shard_zh=_render(chinese.get("shard_loc"), shard_replacements) if has_shard else "",
        behavior=str(english.get("behavior") or ""),
        target_team=english.get("target_team"),
        target_type=english.get("target_type"),
        flags=english.get("flags"),
        damage=english.get("damage"),
        immunity=english.get("immunity"),
        dispellable=english.get("dispellable"),
        max_level=int(english.get("max_level") or 0),
        cast_ranges=_list_value(english.get("cast_ranges")),
        cast_points=_list_value(english.get("cast_points")),
        channel_times=_list_value(english.get("channel_times")),
        cooldowns=_list_value(english.get("cooldowns")),
        durations=_list_value(english.get("durations")),
        damages=_list_value(english.get("damages")),
        mana_costs=_list_value(english.get("mana_costs")),
        gold_costs=_list_value(english.get("gold_costs")),
        health_costs=_list_value(english.get("health_costs")),
        special_values=specials,
        is_item=bool(english.get("is_item")),
        is_innate=bool(english.get("ability_is_innate")),
        has_scepter=has_scepter,
        has_shard=has_shard,
        granted_by_scepter=bool(english.get("ability_is_granted_by_scepter")),
        granted_by_shard=bool(english.get("ability_is_granted_by_shard")),
        is_talent=is_talent,
        hero_ids=sorted({int(hero_id) for hero_id in hero_ids}),
    )


def normalize_hero(
    english: Mapping[str, Any],
    chinese: Mapping[str, Any],
    *,
    aliases: Iterable[str] = (),
) -> HeroCatalogRecord:
    _assert_bilingual_identity(english, chinese, "hero")
    talents = list(english.get("talents") or [])
    talent_tiers = _build_talent_tiers(talents)
    return HeroCatalogRecord(
        hero_id=int(english["id"]),
        internal_name=str(english["name"]),
        name_en=clean_text(english.get("name_loc")),
        name_zh=clean_text(chinese.get("name_loc")),
        aliases=_unique([*aliases, chinese.get("name_loc")]),
        primary_attribute=english.get("primary_attr"),
        complexity=english.get("complexity"),
        attack_capability=english.get("attack_capability"),
        role_levels=_list_value(english.get("role_levels")),
        strength_base=english.get("str_base"),
        strength_gain=english.get("str_gain"),
        agility_base=english.get("agi_base"),
        agility_gain=english.get("agi_gain"),
        intelligence_base=english.get("int_base"),
        intelligence_gain=english.get("int_gain"),
        damage_min=english.get("damage_min"),
        damage_max=english.get("damage_max"),
        attack_rate=english.get("attack_rate"),
        attack_range=english.get("attack_range"),
        projectile_speed=english.get("projectile_speed"),
        armor=english.get("armor"),
        magic_resistance=english.get("magic_resistance"),
        movement_speed=english.get("movement_speed"),
        turn_rate=english.get("turn_rate"),
        sight_range_day=english.get("sight_range_day"),
        sight_range_night=english.get("sight_range_night"),
        max_health=english.get("max_health"),
        health_regen=english.get("health_regen"),
        max_mana=english.get("max_mana"),
        mana_regen=english.get("mana_regen"),
        ability_ids=[int(ability["id"]) for ability in english.get("abilities") or []],
        talent_tiers=talent_tiers,
    )


def normalize_item(
    english: Mapping[str, Any],
    chinese: Mapping[str, Any],
    *,
    aliases: Iterable[str] = (),
    recipe_component_ids: Iterable[int] = (),
    upgrade_item_ids: Iterable[int] = (),
    is_recipe: bool = False,
    neutral_tier: Any = None,
) -> ItemCatalogRecord:
    _assert_bilingual_identity(english, chinese, "item")
    description_en, description_zh = _static_item_descriptions(english, chinese)
    replacements = _value_map(english.get("special_values", []))
    specials = _normalize_special_values(
        english.get("special_values", []), chinese.get("special_values", []), replacements
    )
    detail_neutral_tier = english.get("item_neutral_tier")
    resolved_tier = neutral_tier if neutral_tier is not None else detail_neutral_tier
    return ItemCatalogRecord(
        item_id=int(english["id"]),
        internal_name=str(english["name"]),
        name_en=clean_text(english.get("name_loc")),
        name_zh=clean_text(chinese.get("name_loc")),
        aliases=_unique(aliases),
        description_en=_render(description_en, replacements),
        description_zh=_render(description_zh, replacements),
        lore_en=_render(english.get("lore_loc"), replacements),
        lore_zh=_render(chinese.get("lore_loc"), replacements),
        notes_en=[
            _render(item, replacements) for item in _clean_list(english.get("notes_loc"))
        ],
        notes_zh=[
            _render(item, replacements) for item in _clean_list(chinese.get("notes_loc"))
        ],
        scepter_en=_render(english.get("scepter_loc"), replacements),
        scepter_zh=_render(chinese.get("scepter_loc"), replacements),
        shard_en=_render(english.get("shard_loc"), replacements),
        shard_zh=_render(chinese.get("shard_loc"), replacements),
        price=english.get("item_cost"),
        quality=english.get("item_quality"),
        stock=english.get("item_stock_max"),
        initial_charges=english.get("item_initial_charges"),
        neutral_tier=resolved_tier,
        behavior=str(english.get("behavior") or ""),
        target_team=english.get("target_team"),
        target_type=english.get("target_type"),
        cooldowns=_list_value(english.get("cooldowns")),
        durations=_list_value(english.get("durations")),
        mana_costs=_list_value(english.get("mana_costs")),
        health_costs=_list_value(english.get("health_costs")),
        special_values=specials,
        recipe_component_ids=sorted({int(item_id) for item_id in recipe_component_ids}),
        upgrade_item_ids=sorted({int(item_id) for item_id in upgrade_item_ids}),
        is_recipe=is_recipe,
        is_neutral=_is_neutral(resolved_tier),
        is_purchasable=bool(english.get("item_cost", 0) and not is_recipe),
    )


def collect_talent_bonuses(
    ability_records: Iterable[Mapping[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Index Datafeed ``special_values[].bonuses`` by talent internal name."""

    candidate_index = index_talent_bonus_candidates(ability_records)
    output: dict[str, dict[str, Any]] = {}
    for (talent_name, field_name), candidates in sorted(candidate_index.items()):
        candidate = _resolve_bonus_candidate(
            talent_name, field_name, candidates, source_scope="ability records"
        )
        output.setdefault(talent_name, {})[field_name] = candidate.value
    return output


def index_talent_bonus_candidates(
    ability_records: Iterable[Mapping[str, Any]],
) -> TalentBonusIndex:
    """Build an auditable bonus index while deduplicating repeated hero records."""

    records = list(ability_records)
    internal_names_by_id: dict[int, str] = {}
    for ability in records:
        ability_id = int(ability["id"])
        internal_name = str(ability.get("name") or "")
        existing_name = internal_names_by_id.setdefault(ability_id, internal_name)
        if existing_name != internal_name:
            raise CatalogValidationError(
                f"ability {ability_id} has conflicting internal names while indexing talent bonuses"
            )

    mutable_index: dict[tuple[str, str], list[TalentBonusCandidate]] = {}
    for ability in sorted(
        records,
        key=lambda item: (
            int(item["id"]),
            str(item.get("name") or ""),
            repr(item.get("special_values") or []),
        ),
    ):
        ability_id = int(ability["id"])
        internal_name = str(ability.get("name") or "")
        for special in ability.get("special_values") or []:
            field_name = str(special.get("name") or "")
            if not field_name:
                continue
            for bonus in special.get("bonuses") or []:
                talent_name = str(bonus.get("name") or "")
                if not talent_name:
                    continue
                candidate = TalentBonusCandidate(
                    source_ability_id=ability_id,
                    source_internal_name=internal_name,
                    field_name=field_name,
                    value=bonus.get("value"),
                    operation=int(bonus.get("operation") or 0),
                )
                candidates = mutable_index.setdefault((talent_name, field_name), [])
                if candidate not in candidates:
                    candidates.append(candidate)

    return {
        key: tuple(
            sorted(
                candidates,
                key=lambda item: (
                    item.source_ability_id,
                    item.source_internal_name,
                    item.field_name,
                    repr(item.value),
                    item.operation,
                ),
            )
        )
        for key, candidates in mutable_index.items()
    }


def resolve_talent_bonus_requirements(
    talent: Mapping[str, Any],
    primary_index: TalentBonusIndex,
    auxiliary_index: TalentBonusIndex,
    *,
    localized_talents: Iterable[Mapping[str, Any]] = (),
) -> dict[str, dict[str, Any]]:
    """Resolve display tokens from hero-owned bonuses, then official auxiliaries."""

    talent_name = str(talent.get("name") or "")
    if not talent_name:
        raise CatalogValidationError("talent record is missing an internal name")

    own_values = _value_map(talent.get("special_values", []))
    resolved: dict[str, Any] = {}
    required_tokens = {
        token
        for localized_talent in (talent, *localized_talents)
        for token in _display_tokens(localized_talent)
    }
    for token in sorted(required_tokens):
        if token in own_values:
            continue
        primary_candidates = _bonus_candidates_for_token(primary_index, talent_name, token)
        if primary_candidates:
            candidate = _resolve_bonus_candidate(
                talent_name, token, primary_candidates, source_scope="hero abilities"
            )
        else:
            auxiliary_candidates = _bonus_candidates_for_token(
                auxiliary_index, talent_name, token
            )
            if not auxiliary_candidates:
                raise CatalogValidationError(
                    f"talent {talent_name!r} token {token!r} has no official bonus source"
                )
            candidate = _resolve_bonus_candidate(
                talent_name,
                token,
                auxiliary_candidates,
                source_scope="auxiliary abilities",
            )
        existing = resolved.get(candidate.field_name)
        if existing is not None and existing != candidate.value:
            raise CatalogValidationError(
                f"talent {talent_name!r} field {candidate.field_name!r} resolved inconsistently"
            )
        resolved[candidate.field_name] = candidate.value
    return {talent_name: resolved}


def validate_catalog(
    manifest: CatalogManifest,
    heroes: Sequence[HeroCatalogRecord],
    abilities: Sequence[AbilityCatalogRecord],
    items: Sequence[ItemCatalogRecord],
) -> None:
    """Validate IDs, hero relations, talent closure, recipes, and counts."""

    _require_unique([hero.hero_id for hero in heroes], "hero")
    _require_unique([ability.ability_id for ability in abilities], "ability")
    _require_unique([item.item_id for item in items], "item")
    hero_ids = {hero.hero_id for hero in heroes}
    ability_by_id = {ability.ability_id: ability for ability in abilities}
    item_ids = {item.item_id for item in items}

    for hero in heroes:
        _require_unique(hero.ability_ids, f"hero {hero.hero_id} ability")
        talent_ids = [
            talent_id
            for tier in hero.talent_tiers
            for talent_id in (tier.left_ability_id, tier.right_ability_id)
        ]
        _require_unique(talent_ids, f"hero {hero.hero_id} talent")
        for ability_id in hero.ability_ids:
            if ability_id not in ability_by_id:
                raise CatalogValidationError(
                    f"hero {hero.hero_id} references missing ability {ability_id}"
                )
        for tier in hero.talent_tiers:
            for talent_id in (tier.left_ability_id, tier.right_ability_id):
                talent = ability_by_id.get(talent_id)
                if talent is None or not talent.is_talent:
                    raise CatalogValidationError(
                        f"hero {hero.hero_id} references missing/non-talent ability {talent_id}"
                    )
                if hero.hero_id not in talent.hero_ids:
                    raise CatalogValidationError(
                        f"talent {talent_id} is not associated with hero {hero.hero_id}"
                    )

    for ability in abilities:
        if any(hero_id not in hero_ids for hero_id in ability.hero_ids):
            raise CatalogValidationError(f"ability {ability.ability_id} references missing hero")
        for field_name in (
            "name_en",
            "name_zh",
            "description_en",
            "description_zh",
            "lore_en",
            "lore_zh",
            "scepter_en",
            "scepter_zh",
            "shard_en",
            "shard_zh",
        ):
            if _TOKEN_RE.search(getattr(ability, field_name)):
                raise CatalogValidationError(f"ability {ability.ability_id} has unresolved token")
        if any(_TOKEN_RE.search(note) for note in [*ability.notes_en, *ability.notes_zh]):
            raise CatalogValidationError(f"ability {ability.ability_id} has unresolved token")

    upgrade_graph: dict[int, set[int]] = {}
    for item in items:
        for item_id in [*item.recipe_component_ids, *item.upgrade_item_ids]:
            if item_id not in item_ids:
                raise CatalogValidationError(
                    f"item {item.item_id} references missing item {item_id}"
                )
        if item.upgrade_item_ids:
            upgrade_graph[item.item_id] = set(item.upgrade_item_ids)
        for field_name in (
            "name_en",
            "name_zh",
            "description_en",
            "description_zh",
            "lore_en",
            "lore_zh",
            "scepter_en",
            "scepter_zh",
            "shard_en",
            "shard_zh",
        ):
            if _TOKEN_RE.search(getattr(item, field_name)):
                raise CatalogValidationError(f"item {item.item_id} has unresolved token")
        if any(_TOKEN_RE.search(note) for note in [*item.notes_en, *item.notes_zh]):
            raise CatalogValidationError(f"item {item.item_id} has unresolved token")
    _assert_acyclic(upgrade_graph)

    expected = {"heroes": len(heroes), "abilities": len(abilities), "items": len(items)}
    if manifest.entity_counts != expected:
        raise CatalogValidationError(
            f"manifest entity_counts {manifest.entity_counts!r} do not match {expected!r}"
        )


def validate_sync_audit(
    manifest: CatalogManifest,
    audit: CatalogSyncAudit,
    heroes: Sequence[HeroCatalogRecord],
    abilities: Sequence[AbilityCatalogRecord],
    items: Sequence[ItemCatalogRecord],
) -> None:
    if audit.patch != manifest.patch or audit.generated_at != manifest.generated_at:
        raise CatalogValidationError("sync audit patch/generated_at do not match manifest")

    runtime_ids = {
        "hero": {record.hero_id for record in heroes},
        "ability": {record.ability_id for record in abilities},
        "item": {record.item_id for record in items},
    }
    excluded_keys: set[tuple[str, int]] = set()
    for excluded in audit.excluded_entities:
        key = (excluded.entity_type, excluded.entity_id)
        if key in excluded_keys:
            raise CatalogValidationError(f"duplicate sync audit exclusion {key!r}")
        excluded_keys.add(key)
        if excluded.entity_id in runtime_ids[excluded.entity_type]:
            raise CatalogValidationError(
                f"sync audit exclusion {key!r} is still present in runtime catalog"
            )


def _normalize_special_values(
    english_values: Sequence[Mapping[str, Any]],
    chinese_values: Sequence[Mapping[str, Any]],
    replacements: Mapping[str, str],
) -> list[SpecialValue]:
    zh_by_name = {str(value.get("name")): value for value in chinese_values}
    output: list[SpecialValue] = []
    for english in english_values:
        name = str(english.get("name") or "")
        if not name:
            continue
        chinese = zh_by_name.get(name)
        if chinese is None:
            raise CatalogValidationError(f"special value {name!r} missing Chinese record")
        bonuses = [
            SpecialBonus(
                talent_internal_name=str(bonus.get("name") or ""),
                value=bonus.get("value"),
                operation=int(bonus.get("operation") or 0),
            )
            for bonus in english.get("bonuses") or []
        ]
        output.append(
            SpecialValue(
                name=name,
                values=_special_values(english),
                is_percentage=bool(english.get("is_percentage")),
                heading_en=clean_text(english.get("heading_loc")),
                heading_zh=clean_text(chinese.get("heading_loc")),
                bonuses=bonuses,
                rendered_en=_render_values(
                    english.get("values_float") or english.get("values_int")
                ),
                rendered_zh=_render_values(
                    chinese.get("values_float") or chinese.get("values_int")
                ),
            )
        )
    return output


def _special_values(value: Mapping[str, Any]) -> list[Any]:
    for key in ("values_float", "values_int", "values"):
        raw = value.get(key)
        if raw:
            return [_number(item) for item in raw]
    return []


def _value_map(
    values: Sequence[Mapping[str, Any]], *, upgrade_key: str | None = None
) -> dict[str, str]:
    selected: list[tuple[str, str]] = []
    for value in values:
        name = str(value.get("name") or "")
        if not name:
            continue
        selected_values = (
            _upgrade_values(value, upgrade_key) if upgrade_key else _special_values(value)
        )
        selected.append((name, _render_values(selected_values)))

    if upgrade_key:
        return _upgrade_value_alias_map(selected, upgrade_key)

    output: dict[str, str] = {}
    for name, rendered in selected:
        _store_value_aliases(output, name, rendered)
    return output


def _upgrade_values(value: Mapping[str, Any], upgrade_key: str) -> list[Any]:
    raw = value.get(upgrade_key)
    if isinstance(raw, Sequence) and not isinstance(raw, (str, bytes)) and len(raw) > 0:
        return [_number(item) for item in raw]
    return _special_values(value)


def _apply_ability_base_replacement_exceptions(
    ability: Mapping[str, Any], replacements: Mapping[str, str]
) -> dict[str, str]:
    output = dict(replacements)
    if (
        int(ability["id"]) != 1342
        or str(ability.get("name") or "") != "lone_druid_spirit_bear"
    ):
        return output

    values_by_name: dict[str, str] = {}
    for special in ability.get("special_values") or []:
        field_name = str(special.get("name") or "")
        if not field_name:
            continue
        rendered = _render_values(_special_values(special))
        existing = values_by_name.get(field_name)
        if existing is not None and existing != rendered:
            raise CatalogValidationError(
                f"ability 1342 field {field_name!r} has conflicting base values"
            )
        values_by_name[field_name] = rendered

    exact = values_by_name.get("base_magic_resistance")
    source = values_by_name.get("bear_magic_resistance")
    if exact is not None:
        if source is not None and exact != source:
            raise CatalogValidationError(
                "ability 1342 base_magic_resistance conflicts with "
                f"bear_magic_resistance: {exact!r} != {source!r}"
            )
        return output
    if not source:
        return output

    aliases: dict[str, str] = {}
    _store_value_aliases(aliases, "base_magic_resistance", source)
    for alias, value in aliases.items():
        existing = output.get(alias)
        if existing is not None and existing != value:
            raise CatalogValidationError(
                f"ability 1342 base replacement alias {alias!r} conflicts: "
                f"{existing!r} != {value!r}"
            )
        output[alias] = value
    return output


def _localized_ability_notes(
    english: Mapping[str, Any], chinese: Mapping[str, Any]
) -> tuple[list[str], list[str]]:
    notes_en = _clean_list(english.get("notes_loc"))
    notes_zh = _clean_list(chinese.get("notes_loc"))
    if (
        int(english["id"]) != 5016
        or str(english.get("name") or "") != "bloodseeker_blood_bath"
    ):
        return notes_en, notes_zh

    expected_english = (
        "Total time is a %delay% second delay plus a %abilitycastpoint% second cast time."
    )
    current_bad_chinese = (
        "总时间为%delay%秒的施法时间加上%castpoint_tooltip%秒的生效延迟。"
    )
    reviewed_chinese = (
        "总时间为%delay%秒的生效延迟，加上%abilitycastpoint%秒的施法时间。"
    )
    if notes_en != [expected_english]:
        raise CatalogValidationError(
            "ability 5016 authoritative English note drifted; reviewed translation is invalid"
        )
    if notes_zh != [current_bad_chinese]:
        raise CatalogValidationError(
            "ability 5016 target Chinese note drifted; reviewed translation was not applied"
        )
    return notes_en, [reviewed_chinese]


def _static_item_descriptions(
    english: Mapping[str, Any], chinese: Mapping[str, Any]
) -> tuple[Any, Any]:
    description_en = english.get("desc_loc")
    description_zh = chinese.get("desc_loc")
    if (
        int(english["id"]) != 257
        or str(english.get("name") or "") != "item_tome_of_knowledge"
    ):
        return description_en, description_zh

    static_en = (
        "<h1>Use: Enlighten</h1>Grants you %xp_bonus% experience plus %xp_per_use% "
        "per tome consumed by your team after the first two."
    )
    static_zh = (
        "<h1>使用：启迪</h1>直接获得%xp_bonus%点经验值，而且己方在前两本书后每消耗一本"
        "知识之书，将额外获得%xp_per_use%点经验。"
    )
    dynamic_en = "<br><br>Tomes Used By Team: %customval_team_tomes_used%"
    dynamic_zh = "<br><br>己方已使用本数：%customval_team_tomes_used%"
    return (
        _remove_reviewed_dynamic_suffix(
            description_en,
            expected_static=static_en,
            dynamic_suffix=dynamic_en,
            locale="English",
        ),
        _remove_reviewed_dynamic_suffix(
            description_zh,
            expected_static=static_zh,
            dynamic_suffix=dynamic_zh,
            locale="Chinese",
        ),
    )


def _remove_reviewed_dynamic_suffix(
    value: Any,
    *,
    expected_static: str,
    dynamic_suffix: str,
    locale: str,
) -> str:
    text = str(value or "")
    target_count = text.count(dynamic_suffix)
    if target_count != 1:
        raise CatalogValidationError(
            f"item 257 {locale} dynamic tome suffix count is {target_count}, expected 1"
        )
    if not text.endswith(dynamic_suffix):
        raise CatalogValidationError(
            f"item 257 {locale} dynamic tome segment is not the final suffix"
        )
    if text != f"{expected_static}{dynamic_suffix}":
        raise CatalogValidationError(
            f"item 257 {locale} static Enlighten description drifted"
        )
    return text[: -len(dynamic_suffix)]


def _upgrade_value_alias_map(
    selected: Sequence[tuple[str, str]], upgrade_key: str
) -> dict[str, str]:
    output: dict[str, str] = {}
    sources: dict[str, str] = {}

    # Real field names and their normal aliases take priority over aliases
    # derived from a different field's ``bonus_`` spelling.
    for field_name, rendered in selected:
        _store_strict_value_aliases(
            output,
            sources,
            field_name,
            rendered,
            source=f"exact field {field_name!r}",
            upgrade_key=upgrade_key,
        )

    exact_aliases = set(output)
    for field_name, rendered in selected:
        derived_name = f"bonus_{field_name}"
        derived_aliases: dict[str, str] = {}
        _store_value_aliases(derived_aliases, derived_name, rendered)
        for alias, value in derived_aliases.items():
            if alias in exact_aliases:
                continue
            _store_strict_value_alias(
                output,
                sources,
                alias,
                value,
                source=f"derived alias {derived_name!r} from {field_name!r}",
                upgrade_key=upgrade_key,
            )
    return output


def _store_strict_value_aliases(
    output: dict[str, str],
    sources: dict[str, str],
    name: str,
    value: str,
    *,
    source: str,
    upgrade_key: str,
) -> None:
    aliases: dict[str, str] = {}
    _store_value_aliases(aliases, name, value)
    for alias, rendered in aliases.items():
        _store_strict_value_alias(
            output,
            sources,
            alias,
            rendered,
            source=source,
            upgrade_key=upgrade_key,
        )


def _store_strict_value_alias(
    output: dict[str, str],
    sources: dict[str, str],
    alias: str,
    value: str,
    *,
    source: str,
    upgrade_key: str,
) -> None:
    existing = output.get(alias)
    if existing is not None and existing != value:
        raise CatalogValidationError(
            f"{upgrade_key} alias {alias!r} conflicts between "
            f"{sources[alias]}={existing!r} and {source}={value!r}"
        )
    output[alias] = value
    sources.setdefault(alias, source)


def _display_tokens(ability: Mapping[str, Any]) -> list[str]:
    values: list[Any] = [
        ability.get("name_loc"),
        ability.get("desc_loc"),
        ability.get("lore_loc"),
        *(ability.get("notes_loc") or []),
    ]
    if ability.get("ability_has_scepter"):
        values.append(ability.get("scepter_loc"))
    if ability.get("ability_has_shard"):
        values.append(ability.get("shard_loc"))

    tokens: set[str] = set()
    for value in values:
        text = clean_text(value)
        tokens.update(match.group(1) or match.group(2) or "" for match in _TOKEN_RE.finditer(text))
    tokens.discard("")
    return sorted(tokens)


def _bonus_candidates_for_token(
    index: TalentBonusIndex, talent_name: str, token: str
) -> tuple[TalentBonusCandidate, ...]:
    candidates_by_rank: dict[int, list[TalentBonusCandidate]] = {}
    for (indexed_talent, field_name), indexed_candidates in sorted(index.items()):
        if indexed_talent != talent_name:
            continue
        rank = _bonus_token_match_rank(field_name, token)
        if rank is None:
            continue
        candidates = candidates_by_rank.setdefault(rank, [])
        for candidate in indexed_candidates:
            if candidate not in candidates:
                candidates.append(candidate)
    if not candidates_by_rank:
        return ()
    return tuple(candidates_by_rank[min(candidates_by_rank)])


def _bonus_token_match_rank(field_name: str, token: str) -> int | None:
    if token == field_name:
        return 0
    if token == f"bonus_{field_name}":
        return 1

    direct_aliases: dict[str, str] = {}
    _store_value_aliases(direct_aliases, field_name, "")
    if token in direct_aliases:
        return 2

    bonus_aliases: dict[str, str] = {}
    _store_value_aliases(bonus_aliases, f"bonus_{field_name}", "")
    if token in bonus_aliases:
        return 3
    return None


def _resolve_bonus_candidate(
    talent_name: str,
    token: str,
    candidates: Sequence[TalentBonusCandidate],
    *,
    source_scope: str,
) -> TalentBonusCandidate:
    distinct_facts = {
        (_canonical_bonus_value(candidate.value), candidate.operation)
        for candidate in candidates
    }
    if len(candidates) == 0 or len(distinct_facts) != 1:
        sources = [
            (
                candidate.source_ability_id,
                candidate.source_internal_name,
                candidate.field_name,
                candidate.value,
                candidate.operation,
            )
            for candidate in candidates
        ]
        raise CatalogValidationError(
            f"talent {talent_name!r} token {token!r} has "
            f"{len(distinct_facts)} conflicting facts from {len(candidates)} "
            f"{source_scope} bonus sources: {sources!r}"
        )
    return candidates[0]


def _canonical_bonus_value(value: Any) -> tuple[Any, ...]:
    if isinstance(value, Mapping):
        return (
            "mapping",
            tuple(
                (str(key), _canonical_bonus_value(item))
                for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
            ),
        )
    if isinstance(value, (list, tuple)):
        return ("sequence", tuple(_canonical_bonus_value(item) for item in value))
    normalized = _number(value)
    try:
        hash(normalized)
    except TypeError:
        return (type(normalized).__name__, repr(normalized))
    return (type(normalized).__name__, normalized)


def _flatten_talent_bonuses(values: Mapping[str, Mapping[str, Any]]) -> dict[str, str]:
    output: dict[str, str] = {}
    for bonus_map in values.values():
        for field_name, value in bonus_map.items():
            rendered = _render_values(value if isinstance(value, list) else [value])
            _store_value_aliases(output, f"bonus_{field_name}", rendered)
            _store_value_aliases(output, field_name, rendered)
    return output


def _store_value_aliases(output: dict[str, str], name: str, value: str) -> None:
    """Valve varies casing and underscore style in display placeholders."""

    output[name] = value
    output[name.lower()] = value
    output[name.replace("_", "").lower()] = value


def _render(value: Any, replacements: Mapping[str, str]) -> str:
    text = clean_text(value)
    if not text:
        return ""

    def replace(match: re.Match[str]) -> str:
        key = match.group(1) or match.group(2) or ""
        if key not in replacements:
            raise CatalogValidationError(f"unresolved Valve Datafeed token {match.group(0)!r}")
        return replacements[key]

    return re.sub(r"%{2,}", "%", _TOKEN_RE.sub(replace, text))


def _build_talent_tiers(talents: Sequence[Mapping[str, Any]]) -> list[TalentTier]:
    if len(talents) != 8:
        raise CatalogValidationError(f"expected exactly 8 talent records, got {len(talents)}")
    levels = (
        [int(talent["level"]) for talent in talents]
        if all("level" in t for t in talents)
        else []
    )
    if levels:
        if sorted(levels) != [10, 10, 15, 15, 20, 20, 25, 25]:
            raise CatalogValidationError(f"invalid explicit talent levels: {levels!r}")
        grouped = {
            level: [int(t["id"]) for t in talents if int(t["level"]) == level]
            for level in {10, 15, 20, 25}
        }
    else:
        # The Datafeed emits the talent tree from level 25 down to level 10.
        grouped = {
            level: [int(talent["id"]) for talent in talents[index : index + 2]]
            for index, level in zip(range(0, 8, 2), (25, 20, 15, 10), strict=True)
        }
    if any(len(ids) != 2 or any(identifier <= 0 for identifier in ids) for ids in grouped.values()):
        raise CatalogValidationError("each talent tier must contain two positive IDs")
    return [
        TalentTier(level=level, left_ability_id=ids[0], right_ability_id=ids[1])
        for level, ids in sorted(grouped.items())
    ]


def _assert_bilingual_identity(
    english: Mapping[str, Any], chinese: Mapping[str, Any], entity: str
) -> None:
    try:
        english_id = int(english["id"])
        chinese_id = int(chinese["id"])
        english_name = str(english["name"])
        chinese_name = str(chinese["name"])
    except (KeyError, TypeError, ValueError) as exc:
        raise CatalogValidationError(f"{entity} bilingual record is missing ID/name") from exc
    if english_id != chinese_id or english_name != chinese_name:
        raise CatalogValidationError(
            f"{entity} bilingual identity mismatch: {english_id}/{english_name!r} "
            f"vs {chinese_id}/{chinese_name!r}"
        )


def _clean_list(value: Any) -> list[str]:
    if isinstance(value, str):
        value = [value]
    return [clean_text(item) for item in (value or []) if clean_text(item)]


def _list_value(value: Any) -> list[Any]:
    return list(value) if isinstance(value, (list, tuple)) else []


def _number(value: Any) -> Any:
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value


def _render_values(values: Any) -> str:
    return " / ".join(_format_number(_number(value)) for value in (values or []))


def _format_number(value: Any) -> str:
    if isinstance(value, float):
        return f"{value:g}"
    return str(value)


def _is_neutral(tier: Any) -> bool:
    try:
        numeric = int(tier)
    except (TypeError, ValueError):
        return False
    return numeric >= 0 and numeric < 2**32 - 1


def _unique(values: Iterable[Any]) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = clean_text(value)
        key = text.casefold()
        if text and key not in seen:
            seen.add(key)
            output.append(text)
    return output


def _require_unique(values: Iterable[int], entity: str) -> None:
    values = list(values)
    if len(values) != len(set(values)):
        raise CatalogValidationError(f"duplicate {entity} IDs in catalog")


def _assert_acyclic(graph: Mapping[int, set[int]]) -> None:
    visiting: set[int] = set()
    visited: set[int] = set()

    def visit(node: int) -> None:
        if node in visiting:
            raise CatalogValidationError(f"recipe graph contains a cycle at item {node}")
        if node in visited:
            return
        visiting.add(node)
        for child in graph.get(node, set()):
            visit(child)
        visiting.remove(node)
        visited.add(node)

    for node in graph:
        visit(node)
