from __future__ import annotations

import json
from copy import deepcopy

import pytest
from pydantic import ValidationError

from app.integrations.valve.catalog_repository import DotaCatalogRepository
from app.vnext.capabilities.game.data import MissingData
from app.vnext.catalog import UnitCatalog
from app.vnext.providers.opendota.detail_projection import project_game_detail
from tests.vnext.test_game_detail_projection import FIXTURE, player, project, record, source


def test_saved_purchase_and_hero_are_bilingual_without_source_key_fields() -> None:
    raw = json.loads(FIXTURE.read_text())
    before = deepcopy(raw)
    data = project(record(raw))
    hero = next(p for p in data.players if p.identity.player_slot == 1).identity.hero
    assert hero.model_dump() == {"id": 1, "name_zh": "敌法师", "name_en": "Anti-Mage"}
    purchases = next(p for p in data.builds.players if p.player_slot == 1).purchase_events
    manta = next(p for p in purchases if p.time_seconds == 1478)
    assert manta.item.model_dump() == {"id": 147, "name_zh": "幻影斧", "name_en": "Manta Style"}
    assert "item_key" not in manta.model_dump()
    assert raw == before


def test_empty_slots_unknown_ids_and_skill_repeats_have_distinct_meanings() -> None:
    data = project(record(source(players=[player(
        item_0=999999, item_1=0, item_2=None, ability_upgrades_arr=[5003, 0, 5003, 999999],
    )])))
    build = data.builds.players[0]
    assert build.final_loadout.inventory[0].model_dump() == {
        "id": 999999, "name_zh": None, "name_en": None,
    }
    assert build.final_loadout.inventory[1:3] == [None, None]
    assert [a.id for a in build.ability_upgrade_sequence] == [5003, 0, 5003, 999999]
    gaps = {m.path: m for m in data.coverage.missing}
    prefix = "builds.players[0].final_loadout.inventory"
    assert f"{prefix}[1]" not in gaps
    assert gaps[f"{prefix}[0]"].source_value == 999999
    assert gaps[f"{prefix}[2]"].source_path == "players[0].item_2"
    assert gaps[f"{prefix}[2]"].source_value is None


def test_unconvertible_keys_keep_time_enhancement_and_scalar_source_evidence() -> None:
    data = project(record(source(players=[player(
        neutral_item_history=[{
            "time": 995, "item_neutral": "guardian_shell",
            "item_neutral_enhancement": "enhancement_crude",
        }],
        damage={"npc_dota_hero_future_hero": 42},
    )])))
    history = data.builds.players[0].neutral_item_history[0]
    assert history.time_seconds == 995 and history.item is None
    assert history.enhancement.name_en == "Crude"
    target = data.interactions.players[0].damage_by_target[0]
    assert target.target_hero is None and target.value == 42
    gap = next(m for m in data.coverage.missing if m.source_value == "guardian_shell")
    assert gap.source_path == "players[0].neutral_item_history[0].item_neutral"
    assert gap.path == "builds.players[0].neutral_item_history[0].item"
    assert "guardian_shell" not in history.model_dump_json()


@pytest.mark.parametrize("language", ["name_zh", "name_en"])
def test_missing_localized_name_preserves_other_language_and_original_key(
    monkeypatch: pytest.MonkeyPatch, language: str,
) -> None:
    catalog = DotaCatalogRepository.load_default()
    original = catalog.get_item
    monkeypatch.setattr(catalog, "get_item", lambda key: original(key).model_copy(
        update={language: ""},
    ))
    data = project_game_detail(record(source(players=[player(
        purchase_log=[{"time": 1, "key": "manta"}],
    )])), catalog=catalog, units=UnitCatalog.load_default())
    item = data.builds.players[0].purchase_events[0].item
    assert item.id == 147 and getattr(item, language) is None
    other = "name_en" if language == "name_zh" else "name_zh"
    assert getattr(item, other) == getattr(original(147), other)
    gap = next(m for m in data.coverage.missing if m.path.endswith(f"item.{language}"))
    assert gap.source_value == "manta"


def test_unexpected_catalog_failure_does_not_become_unknown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    catalog = DotaCatalogRepository.load_default()

    def fail(_key):
        raise OSError("catalog read failed")

    monkeypatch.setattr(catalog, "get_hero", fail)
    with pytest.raises(OSError, match="catalog read failed"):
        project_game_detail(record(source(players=[player()])), catalog=catalog,
                            units=UnitCatalog.load_default())


def test_coverage_only_serializes_present_scalar_evidence() -> None:
    assert MissingData(path="players", reason="Missing").model_dump() == {
        "path": "players", "reason": "Missing",
    }
    gap = MissingData(path="a", reason="Unknown", source_path="b", source_value=None)
    assert gap.model_dump()["source_value"] is None
    with pytest.raises(ValidationError):
        MissingData(path="a", reason="Unknown", source_path="b")
    with pytest.raises(ValidationError):
        MissingData(path="a", reason="Unknown", source_path="b", source_value={"raw": []})
