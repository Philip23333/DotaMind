from __future__ import annotations

import json

from app.integrations.valve.catalog_repository import DotaCatalogRepository
from app.vnext.providers.opendota.detail_projection import project_game_detail
from tests.vnext.test_game_detail_projection import FIXTURE, player, record, source


def test_saved_game_interactions_keep_only_heroes_and_exact_catalog_matches() -> None:
    raw = json.loads(FIXTURE.read_text())
    hero_ids = {h.internal_name: h.hero_id
                for h in DotaCatalogRepository.load_default().list_heroes()}
    data = project_game_detail(record(raw), hero_ids=hero_ids)
    p = next(p for p in data.interactions.players if p.player_slot == 1)
    assert len(p.kills_by_target) == 3
    target = next(t for t in p.kills_by_target if t.target_unit_key == "npc_dota_hero_monkey_king")
    assert (target.target_hero_id, target.value) == (114, 1)
    original = next(p for p in raw["players"] if p["player_slot"] == 1)
    assert {t.target_unit_key: t.value for t in p.damage_by_target} == {
        key: value for key, value in original["damage"].items() if key.startswith("npc_dota_hero_")
    }
    assert all(t.target_unit_key.startswith("npc_dota_hero_") for t in p.kills_by_target)


def test_direct_damage_values_self_healing_and_unknown_hero_keys() -> None:
    p = player(
        killed={"npc_dota_creep_badguys_ranged": 42, "npc_dota_hero_antimage": 0},
        damage={"npc_dota_hero_antimage": 100, "npc_dota_hero_future_hero": 20},
        damage_targets={"ability": {"npc_dota_hero_antimage": 999}},
        healing={"npc_dota_hero_antimage": 10},
    )
    data = project_game_detail(record(source(players=[p])),
                               hero_ids={"npc_dota_hero_antimage": 1})
    interactions = data.interactions.players[0]
    assert [t.value for t in interactions.kills_by_target] == [0]
    assert [t.value for t in interactions.damage_by_target] == [100, 20]
    assert [t.target_hero_id for t in interactions.damage_by_target] == [1, None]
    assert interactions.healing_by_target[0].value == 10
    assert interactions.healing_by_target[0].target_hero_id == 1


def test_missing_invalid_and_explicit_empty_maps_do_not_become_zero_pairs() -> None:
    data = project_game_detail(record(source(players=[player(
        killed=None, damage={"npc_dota_hero_antimage": False}, healing={},
    )])))
    p = data.interactions.players[0]
    assert p.kills_by_target is None
    assert p.damage_by_target is None
    assert p.healing_by_target == []
    assert {m.path for m in data.coverage.missing} >= {
        "interactions.players[0].kills_by_target", "interactions.players[0].damage_by_target",
    }
