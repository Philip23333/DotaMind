from __future__ import annotations

from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime, timezone
from threading import Barrier, Event, Lock
from typing import Any

import pytest

from app.integrations.valve import game_data_sync
from app.integrations.valve.catalog import CatalogValidationError
from app.integrations.valve.fetch_session import ValveFetchSession


def _source_responses() -> dict[tuple[Any, ...], dict[str, Any]]:
    talents_en = [
        {
            "id": identifier,
            "name": f"special_bonus_{identifier}",
            "name_loc": "+{s:bonus_damage} Talent" if identifier == 101 else "+Talent",
            "special_values": (
                [] if identifier == 101 else [{"name": "value", "values_float": [identifier]}]
            ),
        }
        for identifier in range(101, 109)
    ]
    talents_zh = [
        dict(
            talent,
            name_loc="+{s:bonus_damage} 天赋" if talent["id"] == 101 else "+天赋",
        )
        for talent in talents_en
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
            {"name": "damage_bonus", "values_float": [10, 20], "bonuses": []},
            {
                "name": "damage",
                "values_float": [0],
                "bonuses": [{"name": "special_bonus_101", "value": 5, "operation": 0}],
            },
        ],
        "ability_is_innate": False,
        "ability_has_scepter": True,
    }
    ability_zh = dict(
        ability_en,
        name_loc="测试技能",
        desc_loc="造成 %damage_bonus%%% 点伤害。",
        lore_loc="一个古老的技能。",
        scepter_loc="神杖：+{s:damage_bonus}",
        special_values=[
            {"name": "damage_bonus", "values_float": [10, 20], "heading_loc": "伤害"},
            {
                "name": "damage",
                "values_float": [0],
                "heading_loc": "伤害",
                "bonuses": [{"name": "special_bonus_101", "value": 5, "operation": 0}],
            },
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
    hero_zh = dict(
        hero_en,
        name_loc="测试英雄",
        abilities=[ability_zh],
        talents=talents_zh,
    )

    ascetic_summary_en = {
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
    ascetic_summary_zh = dict(ascetic_summary_en, name_loc="苦行者头巾")
    ascetic_detail_status = {
        "is_item": True,
        "item_cost": 0,
        "item_initial_charges": 0,
        "item_neutral_tier": 4294967295,
        "item_stock_max": 0,
        "item_stock_time": 0,
        "item_quality": 1,
    }
    ascetic_special_values = [{"name": "AbilityCooldown", "values_float": [25]}]
    ascetic_detail_en = {
        "id": 825,
        "name": "item_ascetic_cap",
        "name_loc": "Ascetic's Cap",
        "desc_loc": (
            "<h1>Passive: Endurance</h1>Grant %status_resistance%%% Status Resistance "
            "and %slow_resistance%%% Slow Resistance for %duration% seconds."
        ),
        "special_values": ascetic_special_values,
        **ascetic_detail_status,
    }
    ascetic_detail_zh = dict(
        ascetic_detail_en,
        name_loc="苦行者头巾",
        desc_loc=(
            "<h1>被动：坚韧不拔</h1>获得%status_resistance%%%状态抗性和"
            "%slow_resistance%%%减速抗性，持续%duration%秒。"
        ),
        special_values=[dict(value) for value in ascetic_special_values],
    )

    item_names = {
        "english": {
            1: ("item_blink", "Blink"),
            2: ("item_recipe_blink", "Blink Recipe"),
            3: ("item_component", "Component"),
        },
        "schinese": {
            1: ("item_blink", "闪烁匕首"),
            2: ("item_recipe_blink", "闪烁匕首卷轴"),
            3: ("item_component", "合成材料"),
        },
    }
    item_summaries: dict[str, list[dict[str, Any]]] = {}
    item_details: dict[str, dict[int, dict[str, Any]]] = {}
    for language, names in item_names.items():
        item_summaries[language] = [
            {
                "id": item_id,
                "name": internal_name,
                "name_loc": display_name,
                "recipes": [{"items": [3]}] if item_id == 2 else [],
            }
            for item_id, (internal_name, display_name) in names.items()
        ]
        summary_825 = ascetic_summary_en if language == "english" else ascetic_summary_zh
        item_summaries[language].append(summary_825)
        item_details[language] = {
            item_id: {
                "id": item_id,
                "name": internal_name,
                "name_loc": display_name,
                "desc_loc": "",
                "special_values": [],
                "item_cost": 100 if item_id != 2 else 0,
            }
            for item_id, (internal_name, display_name) in names.items()
        }
        item_details[language][825] = (
            ascetic_detail_en if language == "english" else ascetic_detail_zh
        )

    ability_summaries = [
        {"id": 10, "name": "test_ability", "name_loc": "Test Ability"},
        *[
            {"id": talent["id"], "name": talent["name"], "name_loc": talent["name_loc"]}
            for talent in talents_en
        ],
        {"id": 200, "name": "special_bonus_added", "name_loc": "Added Bonus"},
    ]
    ability_summaries_zh = [
        {"id": 10, "name": "test_ability", "name_loc": "测试技能"},
        *[
            {"id": talent["id"], "name": talent["name"], "name_loc": talent["name_loc"]}
            for talent in talents_zh
        ],
        {"id": 200, "name": "special_bonus_added", "name_loc": "额外加成"},
    ]
    supplement_en = {
        "id": 200,
        "name": "special_bonus_added",
        "name_loc": "Added Bonus",
        "desc_loc": "",
        "special_values": [],
    }
    supplement_zh = dict(supplement_en, name_loc="额外加成")

    def wrap(collection: str, records: list[dict[str, Any]]) -> dict[str, Any]:
        return {"result": {"data": {collection: records}}}

    return {
        ("herolist", "english"): wrap(
            "heroes", [{"id": 1, "name": "npc_dota_hero_test", "name_loc": "Test Hero"}]
        ),
        ("herolist", "schinese"): wrap(
            "heroes", [{"id": 1, "name": "npc_dota_hero_test", "name_loc": "测试英雄"}]
        ),
        ("herodata", 1, "english"): wrap("heroes", [hero_en]),
        ("herodata", 1, "schinese"): wrap("heroes", [hero_zh]),
        ("abilitylist", "english"): wrap("itemabilities", ability_summaries),
        ("abilitylist", "schinese"): wrap("itemabilities", ability_summaries_zh),
        ("abilitydata", 200, "english"): wrap("abilities", [supplement_en]),
        ("abilitydata", 200, "schinese"): wrap("abilities", [supplement_zh]),
        ("itemlist", "english"): wrap("itemabilities", item_summaries["english"]),
        ("itemlist", "schinese"): wrap("itemabilities", item_summaries["schinese"]),
        **{
            ("itemdata", item_id, language): wrap("items", [detail])
            for language, details in item_details.items()
            for item_id, detail in details.items()
        },
    }


class _FakeCatalogClient:
    def __init__(
        self,
        *,
        fail_on: tuple[Any, ...] | None = None,
        assert_ability_after_hero: bool = False,
    ) -> None:
        self.responses = _source_responses()
        self.original_responses = deepcopy(self.responses)
        self.calls: Counter[tuple[Any, ...]] = Counter()
        self._lock = Lock()
        self._active_calls = 0
        self.max_active_calls = 0
        self.hero_details_returned = 0
        self._fail_on = fail_on
        self._assert_ability_after_hero = assert_ability_after_hero

    def _call(self, method: str, *args: Any) -> dict[str, Any]:
        key = (method, *args)
        with self._lock:
            self.calls[key] += 1
            self._active_calls += 1
            self.max_active_calls = max(self.max_active_calls, self._active_calls)

        try:
            if key == self._fail_on:
                raise RuntimeError(f"fake failure at {method}")

            if method == "herodata":
                with self._lock:
                    self.hero_details_returned += 1
            if method == "abilitydata" and self._assert_ability_after_hero:
                assert self.hero_details_returned == 2
            return self.responses[key]
        finally:
            with self._lock:
                self._active_calls -= 1

    def herolist(self, language: str) -> dict[str, Any]:
        return self._call("herolist", language)

    def herodata(self, hero_id: int, language: str) -> dict[str, Any]:
        return self._call("herodata", hero_id, language)

    def abilitylist(self, language: str) -> dict[str, Any]:
        return self._call("abilitylist", language)

    def abilitydata(self, ability_id: int, language: str) -> dict[str, Any]:
        return self._call("abilitydata", ability_id, language)

    def itemlist(self, language: str) -> dict[str, Any]:
        return self._call("itemlist", language)

    def itemdata(self, item_id: int, language: str) -> dict[str, Any]:
        return self._call("itemdata", item_id, language)


def _build(client: _FakeCatalogClient, *, workers: int = 2):
    return game_data_sync._build_catalog_snapshot(
        ValveFetchSession(client, max_concurrency=workers),
        "7.41f",
        workers=workers,
        generated_at=datetime(2026, 10, 1, 0, 0, tzinfo=timezone.utc),
    )


def test_catalog_tasks_run_hero_ability_and_item_branches_with_shared_session(
    monkeypatch,
) -> None:
    client = _FakeCatalogClient(assert_ability_after_hero=True)
    original_responses = deepcopy(client.original_responses)
    original_hero_builder = game_data_sync._build_hero_records
    original_item_builder = game_data_sync._build_item_records
    branch_start_barrier = Barrier(2)

    def build_hero(*args: Any, **kwargs: Any):
        branch_start_barrier.wait(timeout=5)
        return original_hero_builder(*args, **kwargs)

    def build_items(*args: Any, **kwargs: Any):
        branch_start_barrier.wait(timeout=5)
        return original_item_builder(*args, **kwargs)

    with monkeypatch.context() as scoped:
        scoped.setattr(game_data_sync, "_build_hero_records", build_hero)
        scoped.setattr(game_data_sync, "_build_item_records", build_items)
        bundle = _build(client, workers=2)

    assert client.max_active_calls <= 2
    assert client.hero_details_returned == 2
    for key in (
        ("herolist", "english"),
        ("herolist", "schinese"),
        ("abilitylist", "english"),
        ("abilitylist", "schinese"),
        ("itemlist", "english"),
        ("itemlist", "schinese"),
    ):
        assert client.calls[key] == 1
    assert client.calls[("herodata", 1, "english")] == 1
    assert client.calls[("herodata", 1, "schinese")] == 1
    assert client.calls[("abilitydata", 200, "english")] == 1
    assert client.calls[("abilitydata", 200, "schinese")] == 1
    for item_id in (1, 2, 3, 825):
        assert client.calls[("itemdata", item_id, "english")] == 1
        assert client.calls[("itemdata", item_id, "schinese")] == 1
    assert client.responses == original_responses

    assert [hero.hero_id for hero in bundle.heroes] == [1]
    hero = bundle.heroes[0]
    assert hero.ability_ids == [10]
    assert [talent.level for talent in hero.talent_tiers] == [10, 15, 20, 25]
    assert [ability.ability_id for ability in bundle.abilities] == [10, *range(101, 109), 200]
    ability_by_id = {ability.ability_id: ability for ability in bundle.abilities}
    assert ability_by_id[101].is_talent is True
    assert ability_by_id[101].name_en == "+5 Talent"
    assert ability_by_id[200].hero_ids == []
    assert ability_by_id[200].internal_name == "special_bonus_added"
    assert [item.item_id for item in bundle.items] == [1, 2, 3]
    assert [edge.model_dump(mode="json") for edge in bundle.recipes] == [
        {"recipe_item_id": 2, "component_item_ids": [3], "upgrade_item_ids": [1]}
    ]
    assert [entry.entity_id for entry in bundle.sync_audit.excluded_entities] == [825]
    assert bundle.manifest.entity_counts == {"heroes": 1, "abilities": 10, "items": 3}
    assert bundle.manifest.generated_at == bundle.sync_audit.generated_at
    assert bundle.manifest.patch == bundle.sync_audit.patch == "7.41f"


def test_catalog_tasks_complete_with_one_detail_worker() -> None:
    client = _FakeCatalogClient()

    bundle = _build(client, workers=1)

    assert [hero.hero_id for hero in bundle.heroes] == [1]
    assert [item.item_id for item in bundle.items] == [1, 2, 3]
    assert client.max_active_calls == 1


def test_catalog_output_is_independent_of_branch_completion_order(monkeypatch) -> None:
    original_hero_builder = game_data_sync._build_hero_records
    original_item_builder = game_data_sync._build_item_records

    def build_dump(*, items_first: bool) -> dict[str, Any]:
        hero_done = Event()
        items_done = Event()

        def build_hero(*args: Any, **kwargs: Any):
            result = original_hero_builder(*args, **kwargs)
            if items_first:
                assert items_done.wait(timeout=5)
            hero_done.set()
            return result

        def build_items(*args: Any, **kwargs: Any):
            result = original_item_builder(*args, **kwargs)
            if not items_first:
                assert hero_done.wait(timeout=5)
            items_done.set()
            return result

        with monkeypatch.context() as scoped:
            scoped.setattr(game_data_sync, "_build_hero_records", build_hero)
            scoped.setattr(game_data_sync, "_build_item_records", build_items)
            return _build(_FakeCatalogClient(), workers=2).model_dump(mode="json")

    assert build_dump(items_first=True) == build_dump(items_first=False)


@pytest.mark.parametrize(
    "failure_key",
    [
        ("herodata", 1, "english"),
        ("abilitydata", 200, "english"),
        ("itemdata", 2, "english"),
    ],
)
def test_catalog_branch_failure_returns_no_bundle_or_partial_files(
    failure_key: tuple[Any, ...], tmp_path, monkeypatch
) -> None:
    output_dir = tmp_path / "catalog"
    monkeypatch.setattr(game_data_sync, "CATALOG_OUTPUT_DIR", output_dir)
    client = _FakeCatalogClient(fail_on=failure_key)

    with pytest.raises(RuntimeError, match="fake failure"):
        _build(client)

    assert not output_dir.exists()


def test_failed_branch_waits_for_started_branch_before_returning(monkeypatch) -> None:
    item_started = Event()
    release_item = Event()
    item_exited = Event()
    failure_seen = Event()
    original_item_builder = game_data_sync._build_item_records

    def build_items(*args: Any, **kwargs: Any):
        item_started.set()
        try:
            if not release_item.wait(timeout=5):
                raise TimeoutError("test did not release the item branch")
            return original_item_builder(*args, **kwargs)
        finally:
            item_exited.set()

    def fail_ability_branch(*_args: Any, **_kwargs: Any):
        assert item_started.wait(timeout=5)
        failure_seen.set()
        raise RuntimeError("controlled ability branch failure")

    with ThreadPoolExecutor(max_workers=1) as executor:
        with monkeypatch.context() as scoped:
            scoped.setattr(game_data_sync, "_build_item_records", build_items)
            scoped.setattr(game_data_sync, "_build_ability_records", fail_ability_branch)
            build_future = executor.submit(_build, _FakeCatalogClient())
            try:
                assert failure_seen.wait(timeout=5)
                assert item_started.is_set()
                assert not build_future.done()
            finally:
                release_item.set()
            with pytest.raises(RuntimeError, match="controlled ability branch failure"):
                build_future.result(timeout=5)

    assert item_exited.is_set()


def test_bilingual_list_mismatch_fails_before_detail_branches_start() -> None:
    client = _FakeCatalogClient()
    client.responses[("abilitylist", "schinese")]["result"]["data"]["itemabilities"][0][
        "name"
    ] = "different_internal_name"

    with pytest.raises(CatalogValidationError, match="internal names differ"):
        _build(client)

    assert not any(key[0] in {"herodata", "abilitydata", "itemdata"} for key in client.calls)
