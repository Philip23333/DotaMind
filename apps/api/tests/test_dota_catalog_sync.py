from __future__ import annotations

import io
import json
from datetime import datetime, timezone
from typing import Any

import pytest

from app.integrations.valve.catalog import (
    AbilityCatalogRecord,
    CatalogBundle,
    CatalogExcludedEntity,
    CatalogManifest,
    CatalogSyncAudit,
    CatalogValidationError,
    HeroCatalogRecord,
    ItemCatalogRecord,
    collect_talent_bonuses,
    index_talent_bonus_candidates,
    normalize_ability,
    normalize_hero,
    normalize_item,
    resolve_talent_bonus_requirements,
    validate_catalog,
    validate_sync_audit,
)
from app.integrations.valve.catalog_repository import CatalogLookupError, DotaCatalogRepository
from app.integrations.valve.datafeed import ValveDatafeedClient
from scripts import sync_game_data


class _Response(io.BytesIO):
    def __enter__(self) -> _Response:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()


def _response(payload: object) -> _Response:
    return _Response(json.dumps(payload).encode())


def test_datafeed_transport_allowlists_endpoint_and_retries() -> None:
    requests: list[str] = []
    attempts = 0

    def opener(request, *, timeout):
        nonlocal attempts
        attempts += 1
        requests.append(request.full_url)
        if attempts == 1:
            raise OSError("transient")
        assert timeout == 3
        return _response({"result": {"data": {"heroes": []}}})

    client = ValveDatafeedClient(
        timeout_seconds=3,
        max_attempts=2,
        retry_delays_seconds=(0,),
        opener=opener,
        sleep_fn=lambda _delay: None,
    )
    assert client.herolist("schinese")["result"]["data"]["heroes"] == []
    assert attempts == 2
    assert requests[0] == requests[1]
    assert "https://www.dota2.com/datafeed/herolist?language=schinese" == requests[0]

    client.patchnotes("7.41e")
    assert requests[-1].endswith("patchnotes?version=7.41e&language=english")

    with pytest.raises(ValueError, match="unsupported"):
        client.fetch("https://example.test/not-datafeed")
    with pytest.raises(ValueError, match="language"):
        client.herolist("french")
    with pytest.raises(ValueError, match="dotted numeric patch"):
        client.patchnotes("7.41-e")


def test_catalog_image_slug_uses_only_supported_internal_name_prefixes() -> None:
    assert sync_game_data._asset_slug("npc_dota_hero_antimage", "npc_dota_hero_") == "antimage"
    assert sync_game_data._asset_slug("item_blink", "item_") == "blink"

    with pytest.raises(CatalogValidationError, match="invalid image asset name"):
        sync_game_data._asset_slug("item_Blink", "item_")


def _hero_fixture() -> tuple[dict, dict]:
    talents_en = []
    for index in range(101, 109):
        talents_en.append(
            {
                "id": index,
                "name": f"special_bonus_{index}",
                "name_loc": "+{s:bonus_damage} Talent" if index == 101 else "+Talent",
                "special_values": (
                    [] if index == 101 else [{"name": "value", "values_float": [index]}]
                ),
            }
        )
    talents_zh = [
        dict(
            item,
            name_loc="+{s:bonus_damage} 天赋" if item["id"] == 101 else "+天赋",
        )
        for item in talents_en
    ]
    ability_en = {
        "id": 10,
        "name": "test_ability",
        "name_loc": "Test Ability",
        "desc_loc": "Deals %damage_bonus%%% damage.<br><b>Test</b>",
        "lore_loc": "An &amp; old spell.",
        "notes_loc": ["No HTML"],
        "scepter_loc": "Scepter: +{s:damage_bonus}",
        "shard_loc": "",
        "behavior": "24",
        "max_level": 2,
        "cooldowns": [10, 8],
        "special_values": [
            {
                "name": "damage_bonus",
                "values_float": [10, 20],
                "bonuses": [],
            },
            {
                "name": "damage",
                "values_float": [0],
                "bonuses": [{"name": "special_bonus_101", "value": 5, "operation": 0}],
            }
        ],
        "ability_is_innate": True,
        "ability_has_scepter": True,
    }
    ability_zh = dict(
        ability_en,
        name_loc="测试技能",
        desc_loc="造成 %damage_bonus%%% 点伤害。",
        lore_loc="一个古老的技能。",
        scepter_loc="神杖：+{s:damage_bonus}",
        special_values=[
            {
                "name": "damage_bonus",
                "values_float": [10, 20],
                "heading_loc": "伤害",
                "bonuses": [],
            },
            {
                "name": "damage",
                "values_float": [0],
                "heading_loc": "伤害",
                "bonuses": [{"name": "special_bonus_101", "value": 5, "operation": 0}],
            }
        ],
    )
    hero_en = {
        "id": 1,
        "name": "npc_dota_hero_test",
        "name_loc": "Test Hero",
        "str_base": 20,
        "str_gain": 2,
        "abilities": [ability_en],
        "talents": talents_en,
    }
    hero_zh = dict(hero_en, name_loc="测试英雄", abilities=[ability_zh], talents=talents_zh)
    return hero_en, hero_zh


def _catalog_fixture() -> CatalogBundle:
    hero_en, hero_zh = _hero_fixture()
    hero = normalize_hero(hero_en, hero_zh, aliases=["测试"])
    ability_records_en = [hero_en["abilities"][0], *hero_en["talents"]]
    ability_records_zh = [hero_zh["abilities"][0], *hero_zh["talents"]]
    zh_by_id = {item["id"]: item for item in ability_records_zh}
    bonus_index = collect_talent_bonuses(ability_records_en)
    abilities = [
        normalize_ability(
            item,
            zh_by_id[item["id"]],
            hero_ids=[1],
            is_talent=item["id"] != 10,
            talent_bonuses=bonus_index,
        )
        for item in ability_records_en
    ]
    detail = {
        "id": 3,
        "name": "item_test",
        "name_loc": "Test Item",
        "desc_loc": "<h1>Active</h1> +%damage_bonus%%% damage",
        "lore_loc": "Lore",
        "notes_loc": [],
        "special_values": [{"name": "damage_bonus", "values_float": [8]}],
        "item_cost": 100,
    }
    detail_zh = dict(detail, name_loc="测试物品", desc_loc="<h1>主动</h1> +%damage_bonus%%% 伤害")
    item = normalize_item(detail, detail_zh, recipe_component_ids=[1], is_recipe=False)
    component = ItemCatalogRecord(item_id=1, internal_name="item_component", name_en="Component")
    recipe = ItemCatalogRecord(
        item_id=2,
        internal_name="item_recipe_test",
        name_en="Test Item Recipe",
        is_recipe=True,
        upgrade_item_ids=[3],
    )
    manifest = CatalogManifest(
        patch="7.41e",
        generated_at=datetime.now(timezone.utc),
        locales=["english", "schinese"],
        sources=["https://www.dota2.com/datafeed"],
        entity_counts={"heroes": 1, "abilities": len(abilities), "items": 3},
    )
    bundle = CatalogBundle(
        manifest=manifest,
        heroes=[hero],
        abilities=abilities,
        items=[component, recipe, item],
        sync_audit=CatalogSyncAudit(
            patch=manifest.patch,
            generated_at=manifest.generated_at,
        ),
    )
    validate_catalog(bundle.manifest, bundle.heroes, bundle.abilities, bundle.items)
    validate_sync_audit(
        bundle.manifest,
        bundle.sync_audit,
        bundle.heroes,
        bundle.abilities,
        bundle.items,
    )
    return bundle


def test_catalog_normalizes_bilingual_text_talent_bonus_and_talent_tree() -> None:
    bundle = _catalog_fixture()
    hero = bundle.heroes[0]
    assert [tier.level for tier in hero.talent_tiers] == [10, 15, 20, 25]
    ability = next(item for item in bundle.abilities if item.ability_id == 10)
    assert ability.description_en == "Deals 10 / 20% damage.\nTest"
    assert ability.description_zh == "造成 10 / 20% 点伤害。"
    assert ability.scepter_en == "Scepter: +10 / 20"
    talent = next(item for item in bundle.abilities if item.ability_id == 101)
    assert talent.name_en == "+5 Talent"
    assert (
        next(item for item in bundle.items if item.item_id == 3).description_en
        == "Active\n+8% damage"
    )
    assert all("%damage" not in field for field in (ability.description_en, ability.description_zh))


def test_catalog_ignores_inactive_upgrade_text_without_changing_grant_flags() -> None:
    english = {
        "id": 11,
        "name": "test_inactive_upgrade",
        "name_loc": "Inactive Upgrade",
        "shard_loc": "Stale %missing_shard% text",
        "scepter_loc": "Stale %missing_scepter% text",
        "ability_has_shard": False,
        "ability_has_scepter": False,
        "ability_is_granted_by_shard": True,
        "ability_is_granted_by_scepter": True,
        "special_values": [
            {"name": "stale_value", "values_float": [1], "values_shard": [2]},
            {"name": "stalevalue", "values_float": [1], "values_shard": [3]},
        ],
    }

    ability = normalize_ability(english, dict(english, name_loc="非激活升级"))

    assert ability.shard_en == ability.shard_zh == ""
    assert ability.scepter_en == ability.scepter_zh == ""
    assert ability.has_shard is False
    assert ability.has_scepter is False
    assert ability.granted_by_shard is True
    assert ability.granted_by_scepter is True


def test_catalog_uses_upgrade_values_only_for_active_upgrade_text() -> None:
    special_values = [
        {
            "name": "damage",
            "values_float": [10],
            "values_shard": [0],
            "values_scepter": [30],
        }
    ]
    english = {
        "id": 12,
        "name": "test_upgrade_values",
        "name_loc": "Upgrade Values",
        "desc_loc": "Base %damage%",
        "notes_loc": ["Base note %damage%"],
        "shard_loc": "Shard %damage%",
        "scepter_loc": "Scepter %damage%",
        "ability_has_shard": True,
        "ability_has_scepter": True,
        "special_values": special_values,
    }
    chinese = dict(
        english,
        name_loc="升级数值",
        desc_loc="基础 %damage%",
        notes_loc=["基础说明 %damage%"],
        shard_loc="魔晶 %damage%",
        scepter_loc="神杖 %damage%",
        special_values=[dict(special_values[0])],
    )

    ability = normalize_ability(english, chinese)

    assert ability.description_en == "Base 10"
    assert ability.description_zh == "基础 10"
    assert ability.notes_en == ["Base note 10"]
    assert ability.notes_zh == ["基础说明 10"]
    assert ability.shard_en == "Shard 0"
    assert ability.shard_zh == "魔晶 0"
    assert ability.scepter_en == "Scepter 30"
    assert ability.scepter_zh == "神杖 30"
    assert ability.special_values[0].values == [10]
    assert ability.special_values[0].rendered_en == "10"


def test_catalog_derives_bonus_aliases_for_active_upgrade_values() -> None:
    special_values = [
        {
            "name": "AbilityCooldown",
            "values_float": [50],
            "values_scepter": [40],
            "values_shard": [],
        },
        {
            "name": "radius",
            "values_float": [100],
            "values_scepter": [],
            "values_shard": [0],
        },
        {
            "name": "fallback",
            "values_float": [7],
            "values_scepter": [],
            "values_shard": [],
        },
    ]
    english = {
        "id": 14,
        "name": "test_upgrade_bonus_aliases",
        "name_loc": "Upgrade Bonus Aliases",
        "desc_loc": "Base %AbilityCooldown% / %radius% / %fallback%",
        "scepter_loc": "Scepter %bonus_AbilityCooldown% / {s:bonus_fallback}",
        "shard_loc": "Shard {s:bonus_radius} / %bonus_fallback%",
        "ability_has_scepter": True,
        "ability_has_shard": True,
        "special_values": special_values,
    }
    chinese = dict(
        english,
        name_loc="升级派生别名",
        desc_loc="基础 %AbilityCooldown% / %radius% / %fallback%",
        scepter_loc="神杖 %bonus_AbilityCooldown% / {s:bonus_fallback}",
        shard_loc="魔晶 {s:bonus_radius} / %bonus_fallback%",
        special_values=[dict(value) for value in special_values],
    )

    ability = normalize_ability(english, chinese)

    assert ability.description_en == "Base 50 / 100 / 7"
    assert ability.scepter_en == "Scepter 40 / 7"
    assert ability.scepter_zh == "神杖 40 / 7"
    assert ability.shard_en == "Shard 0 / 7"
    assert ability.shard_zh == "魔晶 0 / 7"
    assert [value.values for value in ability.special_values] == [[50], [100], [7]]


def test_catalog_real_bonus_field_overrides_derived_upgrade_alias() -> None:
    special_values = [
        {
            "name": "AbilityCooldown",
            "values_float": [50],
            "values_scepter": [40],
        },
        {
            "name": "bonus_AbilityCooldown",
            "values_float": [30],
            "values_scepter": [25],
        },
    ]
    english = {
        "id": 15,
        "name": "test_real_bonus_field",
        "name_loc": "Real Bonus Field",
        "scepter_loc": "Scepter %bonus_AbilityCooldown%",
        "ability_has_scepter": True,
        "special_values": special_values,
    }
    chinese = dict(
        english,
        name_loc="真实奖励字段",
        scepter_loc="神杖 %bonus_AbilityCooldown%",
        special_values=[dict(value) for value in special_values],
    )

    ability = normalize_ability(english, chinese)

    assert ability.scepter_en == "Scepter 25"
    assert ability.scepter_zh == "神杖 25"


def test_catalog_rejects_conflicting_real_upgrade_field_aliases() -> None:
    special_values = [
        {"name": "damage_bonus", "values_float": [10], "values_scepter": [20]},
        {"name": "damagebonus", "values_float": [10], "values_scepter": [30]},
    ]
    english = {
        "id": 16,
        "name": "test_conflicting_upgrade_alias",
        "name_loc": "Conflicting Upgrade Alias",
        "scepter_loc": "Scepter %damagebonus%",
        "ability_has_scepter": True,
        "special_values": special_values,
    }

    with pytest.raises(
        CatalogValidationError,
        match="values_scepter alias 'damagebonus' conflicts",
    ):
        normalize_ability(
            english,
            dict(
                english,
                name_loc="升级别名冲突",
                special_values=[dict(value) for value in special_values],
            ),
        )


def test_catalog_resolves_lone_druid_bear_magic_resistance_note_exception() -> None:
    english = {
        "id": 1342,
        "name": "lone_druid_spirit_bear",
        "name_loc": "Summon Spirit Bear",
        "notes_loc": ["The bear has %base_magic_resistance%%% magic resistance."],
        "special_values": [
            {"name": "bear_magic_resistance", "values_float": [25]}
        ],
    }
    chinese = dict(
        english,
        name_loc="熊灵伙伴",
        notes_loc=["熊灵拥有 %base_magic_resistance%%% 魔法抗性。"],
        special_values=[dict(english["special_values"][0])],
    )

    ability = normalize_ability(english, chinese)

    assert ability.notes_en == ["The bear has 25% magic resistance."]
    assert ability.notes_zh == ["熊灵拥有 25% 魔法抗性。"]
    assert ability.special_values[0].name == "bear_magic_resistance"
    assert ability.special_values[0].values == [25]


@pytest.mark.parametrize(
    ("ability_id", "internal_name"),
    [
        (999, "lone_druid_spirit_bear"),
        (1342, "another_spirit_bear"),
    ],
)
def test_catalog_does_not_apply_lone_druid_exception_to_other_abilities(
    ability_id: int, internal_name: str
) -> None:
    english = {
        "id": ability_id,
        "name": internal_name,
        "name_loc": "Other Ability",
        "notes_loc": ["Resistance %base_magic_resistance%"],
        "special_values": [
            {"name": "bear_magic_resistance", "values_float": [25]}
        ],
    }

    with pytest.raises(CatalogValidationError, match="unresolved"):
        normalize_ability(english, dict(english, name_loc="其他技能"))


def test_catalog_lone_druid_exception_requires_real_source_field() -> None:
    english = {
        "id": 1342,
        "name": "lone_druid_spirit_bear",
        "name_loc": "Summon Spirit Bear",
        "notes_loc": ["Resistance %base_magic_resistance%"],
        "special_values": [{"name": "other_value", "values_float": [25]}],
    }

    with pytest.raises(CatalogValidationError, match="unresolved"):
        normalize_ability(english, dict(english, name_loc="熊灵伙伴"))


def test_catalog_lone_druid_exact_field_precedes_exception_and_conflicts_fail() -> None:
    exact_only = {
        "id": 1342,
        "name": "lone_druid_spirit_bear",
        "name_loc": "Summon Spirit Bear",
        "notes_loc": ["Resistance %base_magic_resistance%"],
        "special_values": [
            {"name": "base_magic_resistance", "values_float": [30]}
        ],
    }
    ability = normalize_ability(exact_only, dict(exact_only, name_loc="熊灵伙伴"))
    assert ability.notes_en == ["Resistance 30"]

    conflicting = dict(
        exact_only,
        special_values=[
            {"name": "base_magic_resistance", "values_float": [30]},
            {"name": "bear_magic_resistance", "values_float": [25]},
        ],
    )
    with pytest.raises(CatalogValidationError, match="base_magic_resistance conflicts"):
        normalize_ability(
            conflicting,
            dict(
                conflicting,
                name_loc="熊灵伙伴",
                special_values=[dict(value) for value in conflicting["special_values"]],
            ),
        )


def _blood_rite_note_fixture() -> tuple[dict, dict]:
    special_values = [
        {"name": "delay", "values_float": [4.2]},
        {"name": "AbilityCastPoint", "values_float": [0.75]},
    ]
    english = {
        "id": 5016,
        "name": "bloodseeker_blood_bath",
        "name_loc": "Blood Rite",
        "notes_loc": [
            "Total time is a %delay% second delay plus a "
            "%abilitycastpoint% second cast time."
        ],
        "special_values": special_values,
    }
    chinese = dict(
        english,
        name_loc="血祭",
        notes_loc=[
            "总时间为%delay%秒的施法时间加上%castpoint_tooltip%秒的生效延迟。"
        ],
        special_values=[dict(value) for value in special_values],
    )
    return english, chinese


def test_catalog_applies_reviewed_blood_rite_chinese_note_with_dynamic_values() -> None:
    english, chinese = _blood_rite_note_fixture()

    ability = normalize_ability(english, chinese)

    assert ability.notes_en == [
        "Total time is a 4.2 second delay plus a 0.75 second cast time."
    ]
    assert ability.notes_zh == ["总时间为4.2秒的生效延迟，加上0.75秒的施法时间。"]


def test_catalog_does_not_apply_blood_rite_note_to_other_abilities() -> None:
    english, chinese = _blood_rite_note_fixture()
    english = dict(english, id=999)
    chinese = dict(chinese, id=999)

    with pytest.raises(CatalogValidationError, match="unresolved"):
        normalize_ability(english, chinese)


def test_catalog_rejects_blood_rite_english_note_drift() -> None:
    english, chinese = _blood_rite_note_fixture()
    english = dict(english, notes_loc=["Updated authoritative note."])

    with pytest.raises(CatalogValidationError, match="authoritative English note drifted"):
        normalize_ability(english, chinese)


@pytest.mark.parametrize(
    "notes_zh",
    [
        [],
        ["意外的中文说明。"],
        [
            "总时间为%delay%秒的施法时间加上%castpoint_tooltip%秒的生效延迟。",
            "额外说明。",
        ],
    ],
)
def test_catalog_rejects_blood_rite_target_note_drift(notes_zh: list[str]) -> None:
    english, chinese = _blood_rite_note_fixture()
    chinese = dict(chinese, notes_loc=notes_zh)

    with pytest.raises(CatalogValidationError, match="target Chinese note drifted"):
        normalize_ability(english, chinese)


def _tome_description_fixture() -> tuple[dict, dict]:
    special_values = [
        {"name": "xp_bonus", "values_float": [900]},
        {"name": "xp_per_use", "values_float": [175]},
    ]
    english = {
        "id": 257,
        "name": "item_tome_of_knowledge",
        "name_loc": "Tome of Knowledge",
        "desc_loc": (
            "<h1>Use: Enlighten</h1>Grants you %xp_bonus% experience plus %xp_per_use% "
            "per tome consumed by your team after the first two.<br><br>"
            "Tomes Used By Team: %customval_team_tomes_used%"
        ),
        "special_values": special_values,
    }
    chinese = dict(
        english,
        name_loc="知识之书",
        desc_loc=(
            "<h1>使用：启迪</h1>直接获得%xp_bonus%点经验值，而且己方在前两本书后每消耗一本"
            "知识之书，将额外获得%xp_per_use%点经验。<br><br>"
            "己方已使用本数：%customval_team_tomes_used%"
        ),
        special_values=[dict(value) for value in special_values],
    )
    return english, chinese


def test_catalog_removes_tome_runtime_state_and_renders_dynamic_xp_values() -> None:
    english, chinese = _tome_description_fixture()

    item = normalize_item(english, chinese)

    assert item.description_en == (
        "Use: Enlighten\n"
        "Grants you 900 experience plus 175 per tome consumed by your team after the first two."
    )
    assert item.description_zh == (
        "使用：启迪\n"
        "直接获得900点经验值，而且己方在前两本书后每消耗一本知识之书，将额外获得175点经验。"
    )
    assert "customval" not in item.description_en
    assert "customval" not in item.description_zh


def test_catalog_does_not_remove_tome_runtime_state_from_other_items() -> None:
    english, chinese = _tome_description_fixture()
    english = dict(english, id=258, name="item_other_tome")
    chinese = dict(chinese, id=258, name="item_other_tome")

    with pytest.raises(CatalogValidationError, match="unresolved"):
        normalize_item(english, chinese)


def test_catalog_rejects_tome_static_source_drift() -> None:
    english, chinese = _tome_description_fixture()
    english = dict(english, desc_loc=english["desc_loc"].replace("Grants you", "Gives you"))

    with pytest.raises(CatalogValidationError, match="static Enlighten description drifted"):
        normalize_item(english, chinese)


@pytest.mark.parametrize("target_count", [0, 2])
def test_catalog_rejects_missing_or_multiple_tome_dynamic_targets(target_count: int) -> None:
    english, chinese = _tome_description_fixture()
    suffix = "<br><br>Tomes Used By Team: %customval_team_tomes_used%"
    static = english["desc_loc"].removesuffix(suffix)
    english = dict(english, desc_loc=f"{static}{suffix * target_count}")

    with pytest.raises(
        CatalogValidationError,
        match=f"dynamic tome suffix count is {target_count}, expected 1",
    ):
        normalize_item(english, chinese)


def test_catalog_rejects_tome_dynamic_target_that_is_not_final_suffix() -> None:
    english, chinese = _tome_description_fixture()
    english = dict(english, desc_loc=f"{english['desc_loc']}<br>Unexpected text")

    with pytest.raises(CatalogValidationError, match="not the final suffix"):
        normalize_item(english, chinese)


def test_catalog_renders_bilingual_item_note_tokens_from_special_values() -> None:
    special_values = [
        {"name": "lifesteal_creeps_tooltip", "values_float": [12]}
    ]
    english = {
        "id": 81,
        "name": "item_test_lifesteal",
        "name_loc": "Test Lifesteal Item",
        "notes_loc": ["Creep lifesteal: %lifesteal_creeps_tooltip%%%"],
        "special_values": special_values,
    }
    chinese = dict(
        english,
        name_loc="测试吸血物品",
        notes_loc=["对非英雄单位吸血：%lifesteal_creeps_tooltip%%%"],
        special_values=[dict(value) for value in special_values],
    )

    item = normalize_item(english, chinese)

    assert item.notes_en == ["Creep lifesteal: 12%"]
    assert item.notes_zh == ["对非英雄单位吸血：12%"]
    assert all("lifesteal_creeps_tooltip" not in note for note in item.notes_en)
    assert all("lifesteal_creeps_tooltip" not in note for note in item.notes_zh)


def test_catalog_rejects_unresolved_item_note_token_without_fallback() -> None:
    english = {
        "id": 82,
        "name": "item_missing_note_value",
        "name_loc": "Missing Note Value",
        "notes_loc": ["Missing %lifesteal_creeps_tooltip%"],
        "special_values": [],
    }
    chinese = dict(
        english,
        name_loc="缺失说明数值",
        notes_loc=["缺失 %lifesteal_creeps_tooltip%"],
    )

    with pytest.raises(CatalogValidationError, match="unresolved Valve Datafeed token"):
        normalize_item(english, chinese)


def _ascetic_cap_exclusion_fixture() -> tuple[dict, dict, dict, dict]:
    summary_en = {
        "id": 825,
        "name": "item_ascetic_cap",
        "name_loc": "Ascetic's Cap",
        "neutral_item_tier": -1,
        "is_pregame_suggested": False,
        "is_earlygame_suggested": False,
        "is_lategame_suggested": False,
        "recipes": [],
        "is_innate": False,
    }
    summary_zh = dict(summary_en, name_loc="苦行者头巾")
    detail_status = {
        "is_item": True,
        "item_cost": 0,
        "item_initial_charges": 0,
        "item_neutral_tier": 4294967295,
        "item_stock_max": 0,
        "item_stock_time": 0,
        "item_quality": 1,
    }
    special_values = [{"name": "AbilityCooldown", "values_float": [25]}]
    detail_en = {
        "id": 825,
        "name": "item_ascetic_cap",
        "name_loc": "Ascetic's Cap",
        "desc_loc": (
            "<h1>Passive: Endurance</h1>Grant %status_resistance%%% Status Resistance "
            "and %slow_resistance%%% Slow Resistance for %duration% seconds."
        ),
        "special_values": special_values,
        **detail_status,
    }
    detail_zh = dict(
        detail_en,
        name_loc="苦行者头巾",
        desc_loc=(
            "<h1>被动：坚韧不拔</h1>获得%status_resistance%%%状态抗性和"
            "%slow_resistance%%%减速抗性，持续%duration%秒。"
        ),
        special_values=[dict(value) for value in special_values],
    )
    return summary_en, summary_zh, detail_en, detail_zh


def _review_ascetic_fixture(
    summary_en: dict,
    summary_zh: dict,
    detail_en: dict,
    detail_zh: dict,
    *,
    components_by_target: dict[int, set[int]] | None = None,
    upgrades_by_recipe: dict[int, set[int]] | None = None,
    recipe_edges=None,
):
    return sync_game_data._reviewed_catalog_exclusions(
        {825: summary_en},
        {825: summary_zh},
        {825: detail_en},
        {825: detail_zh},
        components_by_target or {},
        upgrades_by_recipe or {},
        recipe_edges or [],
    )


def test_sync_excludes_reviewed_ascetic_cap_into_audit() -> None:
    summary_en, summary_zh, detail_en, detail_zh = _ascetic_cap_exclusion_fixture()

    excluded = _review_ascetic_fixture(summary_en, summary_zh, detail_en, detail_zh)

    assert len(excluded) == 1
    audit = excluded[0]
    assert audit.entity_type == "item"
    assert audit.entity_id == 825
    assert audit.internal_name == "item_ascetic_cap"
    assert audit.classification == "legacy_or_unclassified"
    assert audit.unresolved_tokens_en == [
        "duration",
        "slow_resistance",
        "status_resistance",
    ]
    assert audit.unresolved_tokens_zh == audit.unresolved_tokens_en
    assert audit.raw_description_en == detail_en["desc_loc"]
    assert audit.raw_description_zh == detail_zh["desc_loc"]
    assert audit.official_status_evidence["summary"]["neutral_item_tier"] == -1
    assert audit.official_status_evidence["recipe_graph"]["referencing_edges"] == []


def test_sync_rejects_ascetic_identity_or_channel_drift() -> None:
    summary_en, summary_zh, detail_en, detail_zh = _ascetic_cap_exclusion_fixture()
    with pytest.raises(CatalogValidationError, match="bilingual identity drifted"):
        _review_ascetic_fixture(
            summary_en,
            summary_zh,
            detail_en,
            dict(detail_zh, name="item_changed_cap"),
        )

    with pytest.raises(CatalogValidationError, match="official summary/detail channel changed"):
        sync_game_data._reviewed_catalog_exclusions(
            {825: summary_en},
            {825: summary_zh},
            {825: detail_en},
            {},
            {},
            {},
            [],
        )


def test_sync_rejects_ascetic_token_or_effect_field_drift() -> None:
    summary_en, summary_zh, detail_en, detail_zh = _ascetic_cap_exclusion_fixture()
    with pytest.raises(CatalogValidationError, match="unresolved token set drifted"):
        _review_ascetic_fixture(
            summary_en,
            summary_zh,
            dict(detail_en, desc_loc=detail_en["desc_loc"].replace("%duration%", "5")),
            detail_zh,
        )

    restored_values = [
        *detail_en["special_values"],
        {"name": "status_resistance", "values_float": [40]},
    ]
    with pytest.raises(CatalogValidationError, match="effect special fields changed"):
        _review_ascetic_fixture(
            summary_en,
            summary_zh,
            dict(detail_en, special_values=restored_values),
            dict(detail_zh, special_values=[dict(value) for value in restored_values]),
        )


@pytest.mark.parametrize(
    ("record_kind", "field_name", "value", "error"),
    [
        ("summary", "neutral_item_tier", 4, "summary status drifted"),
        ("summary", "is_lategame_suggested", True, "summary status drifted"),
        ("detail", "item_cost", 100, "detail status drifted"),
        ("detail", "item_neutral_tier", 4, "detail status drifted"),
    ],
)
def test_sync_rejects_ascetic_official_status_drift(
    record_kind: str, field_name: str, value, error: str
) -> None:
    summary_en, summary_zh, detail_en, detail_zh = _ascetic_cap_exclusion_fixture()
    if record_kind == "summary":
        summary_en = dict(summary_en, **{field_name: value})
        summary_zh = dict(summary_zh, **{field_name: value})
    else:
        detail_en = dict(detail_en, **{field_name: value})
        detail_zh = dict(detail_zh, **{field_name: value})

    with pytest.raises(CatalogValidationError, match=error):
        _review_ascetic_fixture(summary_en, summary_zh, detail_en, detail_zh)


def test_sync_rejects_any_ascetic_recipe_reference() -> None:
    summary_en, summary_zh, detail_en, detail_zh = _ascetic_cap_exclusion_fixture()
    edge = sync_game_data.RecipeEdge(
        recipe_item_id=900,
        component_item_ids=[825],
        upgrade_item_ids=[901],
    )

    with pytest.raises(CatalogValidationError, match="recipe graph changed"):
        _review_ascetic_fixture(
            summary_en,
            summary_zh,
            detail_en,
            detail_zh,
            components_by_target={825: {100}},
            recipe_edges=[edge],
        )


def test_catalog_does_not_exclude_other_item_with_ascetic_tokens() -> None:
    _, _, detail_en, detail_zh = _ascetic_cap_exclusion_fixture()
    detail_en = dict(detail_en, id=826, name="item_other_cap")
    detail_zh = dict(detail_zh, id=826, name="item_other_cap")

    with pytest.raises(CatalogValidationError, match="unresolved"):
        normalize_item(detail_en, detail_zh)


@pytest.mark.parametrize(
    ("flag_name", "text_name"),
    [
        ("ability_has_shard", "shard_loc"),
        ("ability_has_scepter", "scepter_loc"),
    ],
)
def test_catalog_rejects_unresolved_token_in_active_upgrade_text(
    flag_name: str, text_name: str
) -> None:
    english = {
        "id": 13,
        "name": "test_missing_upgrade_value",
        "name_loc": "Missing Upgrade Value",
        flag_name: True,
        text_name: "Active %missing% text",
        "special_values": [],
    }

    with pytest.raises(CatalogValidationError, match="unresolved"):
        normalize_ability(english, dict(english, name_loc="缺失升级数值"))


def _talent_fixture(internal_name: str, token: str) -> dict:
    return {
        "id": 900,
        "name": internal_name,
        "name_loc": f"Talent {{s:{token}}}",
        "special_values": [],
    }


def _bonus_source_fixture(
    ability_id: int,
    internal_name: str,
    talent_name: str,
    field_name: str,
    value: Any,
    operation: int = 2,
) -> dict:
    return {
        "id": ability_id,
        "name": internal_name,
        "special_values": [
            {
                "name": field_name,
                "values_float": [1],
                "bonuses": [
                    {"name": talent_name, "value": value, "operation": operation}
                ],
            }
        ],
    }


@pytest.mark.parametrize(
    ("talent_name", "token", "field_name", "helper_name", "value"),
    [
        (
            "special_bonus_test_channel",
            "bonus_AbilityChannelTime",
            "AbilityChannelTime",
            "hidden_teleport_helper",
            0.5,
        ),
        (
            "special_bonus_test_armor",
            "armor_removed",
            "armor_removed",
            "separate_passive_helper",
            8,
        ),
        (
            "special_bonus_test_pull",
            "pull_strength",
            "pull_strength",
            "granted_control_helper",
            12,
        ),
    ],
)
def test_catalog_resolves_three_auxiliary_talent_bonus_shapes(
    talent_name: str,
    token: str,
    field_name: str,
    helper_name: str,
    value: float,
) -> None:
    talent = _talent_fixture(talent_name, token)
    auxiliary = index_talent_bonus_candidates(
        [_bonus_source_fixture(100, helper_name, talent_name, field_name, value)]
    )

    bonuses = resolve_talent_bonus_requirements(talent, {}, auxiliary)
    localized = dict(talent, name_loc=f"天赋 {{s:{token}}}")
    ability = normalize_ability(
        talent,
        localized,
        is_talent=True,
        talent_bonuses=bonuses,
    )

    assert ability.name_en == f"Talent {value:g}"
    assert ability.name_zh == f"天赋 {value:g}"


def test_catalog_prefers_unique_hero_bonus_and_deduplicates_repeated_ability() -> None:
    talent_name = "special_bonus_test_primary"
    talent = _talent_fixture(talent_name, "damage")
    primary_record = _bonus_source_fixture(101, "hero_visible", talent_name, "damage", 5)
    same_fact_other_source = _bonus_source_fixture(
        103, "hero_visible_secondary", talent_name, "damage", 5.0
    )
    primary = index_talent_bonus_candidates(
        [primary_record, dict(primary_record, name_loc="Shared variant"), same_fact_other_source]
    )
    auxiliary = index_talent_bonus_candidates(
        [_bonus_source_fixture(102, "hidden_helper", talent_name, "damage", 99)]
    )

    assert resolve_talent_bonus_requirements(talent, primary, auxiliary) == {
        talent_name: {"damage": 5}
    }
    assert [
        candidate.source_ability_id for candidate in primary[(talent_name, "damage")]
    ] == [101, 103]


def test_catalog_rejects_ambiguous_and_missing_talent_bonus_sources() -> None:
    talent_name = "special_bonus_test_missing"
    talent = _talent_fixture(talent_name, "damage")
    ambiguous = index_talent_bonus_candidates(
        [
            _bonus_source_fixture(201, "helper_a", talent_name, "damage", 5),
            _bonus_source_fixture(202, "helper_b", talent_name, "damage", 6),
        ]
    )

    with pytest.raises(
        CatalogValidationError,
        match="2 conflicting facts from 2 auxiliary abilities bonus sources",
    ):
        resolve_talent_bonus_requirements(talent, {}, ambiguous)
    with pytest.raises(CatalogValidationError, match="no official bonus source"):
        resolve_talent_bonus_requirements(talent, {}, {})
    with pytest.raises(
        CatalogValidationError,
        match="2 conflicting facts from 2 ability records bonus sources",
    ):
        collect_talent_bonuses(
            [
                _bonus_source_fixture(201, "helper_a", talent_name, "damage", 5),
                _bonus_source_fixture(202, "helper_b", talent_name, "damage", 6),
            ]
        )

    operation_conflict = index_talent_bonus_candidates(
        [
            _bonus_source_fixture(203, "helper_c", talent_name, "damage", 5, operation=0),
            _bonus_source_fixture(204, "helper_d", talent_name, "damage", 5, operation=2),
        ]
    )
    with pytest.raises(CatalogValidationError, match="2 conflicting facts"):
        resolve_talent_bonus_requirements(talent, {}, operation_conflict)

    list_conflict = index_talent_bonus_candidates(
        [
            _bonus_source_fixture(205, "helper_e", talent_name, "damage", [5, 6]),
            _bonus_source_fixture(206, "helper_f", talent_name, "damage", [5, 7]),
        ]
    )
    with pytest.raises(CatalogValidationError, match="2 conflicting facts"):
        resolve_talent_bonus_requirements(talent, {}, list_conflict)


def test_catalog_prefers_exact_bonus_field_over_prefixed_alias() -> None:
    talent_name = "special_bonus_test_prefixed_field"
    talent = _talent_fixture(talent_name, "bonus_stack_damage")
    primary = index_talent_bonus_candidates(
        [
            _bonus_source_fixture(
                301, "visible_ability", talent_name, "bonus_stack_damage", 15
            ),
            _bonus_source_fixture(301, "visible_ability", talent_name, "stack_damage", 99),
        ]
    )

    assert resolve_talent_bonus_requirements(talent, primary, {}) == {
        talent_name: {"bonus_stack_damage": 15}
    }


def test_catalog_merges_english_and_chinese_talent_token_requirements() -> None:
    talent_name = "special_bonus_test_localized_token"
    english = _talent_fixture(talent_name, "value")
    english["special_values"] = [{"name": "value", "values_float": [5]}]
    chinese = dict(english, name_loc="天赋 {s:pull_strength}")
    auxiliary = index_talent_bonus_candidates(
        [_bonus_source_fixture(401, "hidden_helper", talent_name, "pull_strength", 12)]
    )

    bonuses = resolve_talent_bonus_requirements(
        english,
        {},
        auxiliary,
        localized_talents=[chinese],
    )
    ability = normalize_ability(
        english,
        chinese,
        is_talent=True,
        talent_bonuses=bonuses,
    )

    assert ability.name_en == "Talent 5"
    assert ability.name_zh == "天赋 12"


def test_sync_filters_auxiliary_ability_requests_without_associating_by_hero_name() -> None:
    summaries = [
        {"id": 0, "name": "dota_base_ability"},
        {"id": 10, "name": "visible_hero_ability"},
        {"id": 20, "name": "known_talent"},
        {"id": 21, "name": "special_bonus_unused_talent"},
        {"id": 30, "name": "item_active"},
        {"id": 40, "name": "unrelated_hidden_helper"},
        {"id": 41, "name": "another_auxiliary"},
    ]

    assert sync_game_data._auxiliary_ability_ids(
        summaries,
        visible_ability_ids={10},
        talent_ids={20},
        item_ids={30},
    ) == [40, 41]


def test_catalog_rejects_unresolved_token_and_bilingual_identity_mismatch() -> None:
    hero_en, hero_zh = _hero_fixture()
    with pytest.raises(CatalogValidationError, match="identity mismatch"):
        normalize_hero(hero_en, dict(hero_zh, name="npc_dota_hero_other"))

    with pytest.raises(CatalogValidationError, match="unresolved"):
        normalize_item(
            {"id": 3, "name": "item_bad", "desc_loc": "%missing%", "special_values": []},
            {"id": 3, "name": "item_bad", "desc_loc": "%missing%", "special_values": []},
        )


def test_snapshot_writer_roundtrips_manifest_catalogs_and_sync_audit(tmp_path, monkeypatch) -> None:
    bundle = _catalog_fixture()
    output = tmp_path / "catalog"
    monkeypatch.setattr(sync_game_data, "CATALOG_OUTPUT_DIR", output)
    sync_game_data._write_catalog_snapshot(bundle)

    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    heroes = json.loads((output / "dota2_heroes.json").read_text(encoding="utf-8"))
    abilities = json.loads((output / "dota2_abilities.json").read_text(encoding="utf-8"))
    items = json.loads((output / "dota2_items.json").read_text(encoding="utf-8"))
    sync_audit = json.loads((output / "sync_audit.json").read_text(encoding="utf-8"))
    CatalogManifest.model_validate(manifest)
    CatalogSyncAudit.model_validate(sync_audit)
    for item in heroes:
        HeroCatalogRecord.model_validate(item)
    for item in abilities:
        AbilityCatalogRecord.model_validate(item)
    for item in items["items"]:
        ItemCatalogRecord.model_validate(item)
    assert len(heroes) == manifest["entity_counts"]["heroes"]
    assert len(abilities) == manifest["entity_counts"]["abilities"]
    assert len(items["items"]) == manifest["entity_counts"]["items"]
    assert {
        "manifest.json",
        "dota2_heroes.json",
        "dota2_abilities.json",
        "dota2_items.json",
        "sync_audit.json",
    } == {
        item.name for item in output.iterdir()
    }


def test_runtime_repository_ignores_audit_and_excluded_item_remains_missing(
    tmp_path, monkeypatch
) -> None:
    bundle = _catalog_fixture()
    bundle.sync_audit = CatalogSyncAudit(
        patch=bundle.manifest.patch,
        generated_at=bundle.manifest.generated_at,
        excluded_entities=[
            CatalogExcludedEntity(
                entity_type="item",
                entity_id=825,
                internal_name="item_ascetic_cap",
                reason="fixture exclusion",
                raw_description_en="%status_resistance%",
                raw_description_zh="%status_resistance%",
                unresolved_tokens_en=["status_resistance"],
                unresolved_tokens_zh=["status_resistance"],
                official_status_evidence={"fixture": True},
            )
        ],
    )
    output = tmp_path / "catalog"
    monkeypatch.setattr(sync_game_data, "CATALOG_OUTPUT_DIR", output)
    sync_game_data._write_catalog_snapshot(bundle)

    repository = DotaCatalogRepository(output)
    with pytest.raises(CatalogLookupError, match="item not found: 825"):
        repository.get_item(825)
    assert repository.resolve_item("Ascetic's Cap")["status"] == "not_found"
