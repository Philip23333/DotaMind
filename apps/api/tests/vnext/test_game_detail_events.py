from __future__ import annotations

import json
from copy import deepcopy

import pytest
from pydantic import ValidationError

from app.integrations.valve.catalog_repository import DotaCatalogRepository
from app.vnext.capabilities.game.data import SourceConflict
from app.vnext.providers.opendota.detail_projection import project_game_detail
from tests.vnext.test_game_detail_projection import FIXTURE, player, record, source


def test_saved_game_event_counts_and_source_conflict_with_exact_catalog_ids() -> None:
    raw = json.loads(FIXTURE.read_text())
    before = deepcopy(raw)
    hero_ids = {hero.internal_name: hero.hero_id
                for hero in DotaCatalogRepository.load_default().list_heroes()}
    data = project_game_detail(record(raw), hero_ids=hero_ids)
    events = data.events
    assert len(events.hero_deaths) == 50
    assert len(events.buybacks) == 3
    assert len(events.building_destructions) == 21
    assert len(events.roshan_kills) == 2
    assert len(events.aegis_pickups) == 2
    assert len(events.other_objectives) == 5
    death = next(d for d in events.hero_deaths if d.victim_player_slot == 1
                 and d.time_seconds == 815)
    assert death.killer_unit_key == "npc_dota_hero_pangolier"
    assert death.killer_hero_id == hero_ids[death.killer_unit_key]
    assert death.killer_player_slot == next(p["player_slot"] for p in raw["players"]
                                          if p["hero_id"] == death.killer_hero_id)
    assert (death.gold_lost, death.gold_fed, death.time_dead_seconds) == (116, 433, 28)
    assert events.first_blood.reported_time_seconds == 0
    assert events.first_blood.objective_events[0].time_seconds == -25
    assert data.coverage.conflicts[0].model_dump() == {
        "paths": ["first_blood_time", "objectives[0].time"], "values": [0, -25],
    }
    assert events.building_destructions[-1].time_seconds == 2905
    assert not any("duration" in m.reason or "2905" in m.reason for m in data.coverage.missing)
    assert events.aegis_pickups[0].player_slot == 128
    assert events.aegis_pickups[0].source_slot == 5
    assert events.roshan_kills[0].source_team == 3
    assert next(e for e in events.other_objectives
                if e.source_type == "CHAT_MESSAGE_MINIBOSS_KILL").source_team == 3
    assert raw == before


def test_deaths_do_not_duplicate_kill_logs_and_do_not_guess_unknown_killers() -> None:
    p = player(kills_log=[{"time": 1}], deaths_log=[
        {"time": 1, "key": "npc_dota_neutral_centaur_khan"},
        {"time": 1, "key": "npc_dota_hero_new_hero"},
    ])
    data = project_game_detail(record(source(players=[p])),
                               hero_ids={"npc_dota_hero_antimage": 1})
    assert len(data.events.hero_deaths) == 2
    assert [e.time_seconds for e in data.events.hero_deaths] == [1, 1]
    assert all(e.killer_hero_id is None and e.killer_player_slot is None
               for e in data.events.hero_deaths)
    assert data.events.hero_deaths[1].killer_unit_key == "npc_dota_hero_new_hero"


def test_partial_player_logs_preserve_other_players_and_known_final_stats() -> None:
    data = project_game_detail(record(source(players=[
        player(deaths_log=None, kills=2),
        player(player_slot=128, deaths_log=[{"time": 10, "key": "unknown"}]),
    ])))
    assert len(data.events.hero_deaths) == 1
    assert data.players[0].final_stats.kills == 2
    assert any(m.path == "events.hero_deaths" and "players[0]" in m.reason
               for m in data.coverage.missing)


def test_empty_and_missing_event_logs_have_different_meanings() -> None:
    missing = project_game_detail(record({"match_id": 123}))
    assert missing.events.hero_deaths is None
    assert missing.events.buybacks is None
    assert missing.events.roshan_kills is None
    empty = project_game_detail(record(source(players=[player()])))
    assert empty.events.hero_deaths == []
    assert empty.events.buybacks == []
    assert empty.events.roshan_kills == []


def test_unknown_objective_codes_and_opaque_actor_codes_remain_source_facts() -> None:
    data = project_game_detail(record(source(players=[player()], objectives=[
        {"type": "UNKNOWN_CODE", "time": 13, "slot": 9, "team": 0, "killer": 8,
         "player_slot": 9, "extra_raw": {"do_not_copy": True}},
        {"type": "CHAT_MESSAGE_AEGIS", "time": 12, "slot": 0},
        {"type": 17, "time": 14},
    ])))
    objective = data.events.other_objectives[0]
    assert (objective.source_type, objective.source_team, objective.source_killer) == (
        "UNKNOWN_CODE", 0, 8,
    )
    assert objective.player_slot is None
    assert data.events.aegis_pickups[0].player_slot is None
    assert data.events.other_objectives[1].source_type == 17
    assert "extra_raw" not in objective.model_dump()


def test_duplicate_hero_or_player_slots_do_not_confirm_a_killer() -> None:
    data = project_game_detail(record(source(players=[
        player(deaths_log=[{"time": 1, "key": "npc_dota_hero_antimage"}]),
        player(player_slot=128),
    ])), hero_ids={"npc_dota_hero_antimage": 1})
    assert data.events.hero_deaths[0].killer_hero_id == 1
    assert data.events.hero_deaths[0].killer_player_slot is None


def test_buyback_owner_and_conflicting_source_slot_are_both_retained() -> None:
    data = project_game_detail(record(source(players=[player(
        buyback_log=[{"time": 0, "slot": 7, "player_slot": 128}],
    )])))
    event = data.events.buybacks[0]
    assert event.player_slot == 0
    assert event.source_player_slot == 128
    assert data.coverage.conflicts[0].values == [0, 128]
    assert event.time_seconds == 0


def test_conflicts_require_corresponding_paths_and_scalar_values() -> None:
    with pytest.raises(ValidationError):
        SourceConflict(paths=["a", "b"], values=[0])
    with pytest.raises(ValidationError):
        SourceConflict(paths=["a", "b"], values=[{}, 0])
