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
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class CatalogValidationError(ValueError):
    """Raised when Valve records cannot form a closed catalog snapshot."""


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


class CatalogBundle(CatalogModel):
    manifest: CatalogManifest
    heroes: list[HeroCatalogRecord]
    abilities: list[AbilityCatalogRecord]
    items: list[ItemCatalogRecord]
    recipes: list[RecipeEdge] = Field(default_factory=list)


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


def normalize_ability(
    english: Mapping[str, Any],
    chinese: Mapping[str, Any],
    *,
    hero_ids: Iterable[int] = (),
    is_talent: bool = False,
    talent_bonuses: Mapping[str, Mapping[str, Any]] | None = None,
) -> AbilityCatalogRecord:
    _assert_bilingual_identity(english, chinese, "ability")
    own_values = _value_map(english.get("special_values", []))
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
        notes_en=[_render(item, replacements) for item in _clean_list(english.get("notes_loc"))],
        notes_zh=[_render(item, replacements) for item in _clean_list(chinese.get("notes_loc"))],
        scepter_en=_render(english.get("scepter_loc"), replacements),
        scepter_zh=_render(chinese.get("scepter_loc"), replacements),
        shard_en=_render(english.get("shard_loc"), replacements),
        shard_zh=_render(chinese.get("shard_loc"), replacements),
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
        has_scepter=bool(english.get("ability_has_scepter")),
        has_shard=bool(english.get("ability_has_shard")),
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
        description_en=_render(english.get("desc_loc"), replacements),
        description_zh=_render(chinese.get("desc_loc"), replacements),
        lore_en=_render(english.get("lore_loc"), replacements),
        lore_zh=_render(chinese.get("lore_loc"), replacements),
        notes_en=_clean_list(english.get("notes_loc")),
        notes_zh=_clean_list(chinese.get("notes_loc")),
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

    output: dict[str, dict[str, Any]] = {}
    for ability in ability_records:
        for special in ability.get("special_values") or []:
            field_name = str(special.get("name") or "")
            if not field_name:
                continue
            for bonus in special.get("bonuses") or []:
                talent_name = str(bonus.get("name") or "")
                if talent_name:
                    output.setdefault(talent_name, {})[field_name] = bonus.get("value")
    return output


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


def _value_map(values: Sequence[Mapping[str, Any]]) -> dict[str, str]:
    output: dict[str, str] = {}
    for value in values:
        name = str(value.get("name") or "")
        if name:
            _store_value_aliases(output, name, _render_values(_special_values(value)))
    return output


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
