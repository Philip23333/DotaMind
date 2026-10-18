"""Source-backed eight-section projection; no live calls in deterministic tests."""

import json
from copy import deepcopy
from pathlib import Path

import pytest

from app.integrations.valve.catalog_repository import DotaCatalogRepository
from app.vnext.capabilities.game.projection import project_detail
from app.vnext.catalog import UnitCatalog
from app.vnext.providers.opendota.detail_entities import DetailEntities
from app.vnext.providers.opendota.game_detail import OpenDotaGameRecord
from app.vnext.providers.stratz.game_detail import StratzGameRecord

FIXTURES = Path(__file__).parent / "fixtures" / "game_detail"


def primary(game_id=8960991322):
    return StratzGameRecord.model_validate_json((FIXTURES / f"stratz_{game_id}.json").read_text())


def project(record, supplement=None):
    return project_detail(
        record,
        supplement,
        entities=DetailEntities(DotaCatalogRepository.load_default()),
        units=UnitCatalog.load_default(),
    )


def supplement(record):
    return OpenDotaGameRecord(
        match_id=record.match_id,
        retrieved_at=record.retrieved_at,
        data=json.loads((FIXTURES / "opendota_9040460429.json").read_text()),
    )


@pytest.mark.parametrize("game_id,expected", [(8960991322, 65), (9040460429, 50), (9040578015, 88)])
def test_live_source_death_counts_ignore_noise_without_fitting_to_totals(game_id, expected):
    record = primary(game_id)
    before = deepcopy(record.data)
    data = project(record)
    assert len(data.events.hero_deaths) == expected
    assert sum(p.final_stats.deaths for p in data.players) == expected
    assert all(c.unaccounted_deaths == 0 for c in data.coverage.death_counts)
    assert all(e.killer_unit is None for e in data.events.hero_deaths)
    assert all(e.source_paths[0].source == "stratz" for e in data.events.hero_deaths)
    assert all(p.final_stats.earned_gold_net_worth_gap is None for p in data.players)
    assert all(p.minute_timeline is None for p in data.players)
    assert record.data == before
    assert "fixture_scope" not in json.dumps(data.model_dump())


def test_death_money_fields_are_not_substituted_and_zero_loss_is_preserved():
    data = project(primary())
    event = next(
        e for e in data.events.hero_deaths if e.victim_player_slot == 0 and e.time_seconds == 2297
    )
    assert event.gold_lost == 282  # DEATH gold amount is -694, a different source quantity.
    assert len(event.source_paths) == 2
    assert any(e.gold_lost == 0 for e in data.events.hero_deaths)
    assert sum(sum(t.value for t in p.kills_by_target) for p in data.interactions.players) == 64


def test_explicit_objectives_do_not_count_gold_reason_as_roshan():
    data = project(primary())
    assert [(e.type, e.time_seconds) for e in data.events.other_objectives] == [
        ("tormentor_kill", 1982),
        ("tormentor_kill", 2839),
    ]
    assert data.events.roshan_kills is None
    assert data.events.aegis_pickups is None
    assert data.events.first_blood.reported_time_seconds == 56
    assert data.events.first_blood.objective_events[0].time_seconds == 79
    assert any(c.values == [56, 79] for c in data.coverage.conflicts)
    assert data.economy.radiant_gold_adv is None


def test_supplement_uses_exact_player_association_and_preserves_income_not_net_worth():
    record = primary(9040460429)
    extra = supplement(record)
    extra.data["players"].reverse()
    data = project(record, extra)
    player = next(p for p in data.players if p.identity.account_id == 321580662)
    node = player.minute_timeline[10]
    assert node.cumulative_gold_earned == 2930 and node.cumulative_experience == 2383
    assert "net_worth" not in node.model_dump() and "deaths" not in node.model_dump()
    assert data.match.score.dire == 33
    assert data.match.teams.radiant.name == "Team Spirit"
    assert data.economy.radiant_gold_adv[-1] == -29518
    assert len(data.events.roshan_kills) == 2
    assert all(e.source_paths[0].source == "opendota" for e in data.events.roshan_kills)
    assert not any(
        m.source == "opendota" and ".final_stats.net_worth" in m.path for m in data.coverage.missing
    )


def test_conflicting_player_identity_does_not_receive_someone_elses_minutes():
    record = primary(9040460429)
    extra = supplement(record)
    extra.data["players"][0]["account_id"] += 1
    data = project(record, extra)
    assert data.players[0].minute_timeline is None
    assert data.players[1].minute_timeline is not None


def test_ambiguous_same_second_death_attributes_remain_unknown_without_dropping_fact():
    record = primary()
    p = record.data["players"][0]
    time = p["playbackData"]["goldEvents"][0]["time"]
    row = next(
        e
        for e in p["playbackData"]["deathEvents"]
        if e["time"] == time and e["target"] == p["heroId"]
    )
    p["playbackData"]["deathEvents"].append(deepcopy(row))
    data = project(record)
    event = next(
        e
        for e in data.events.hero_deaths
        if e.victim_player_slot == 0 and e.time_seconds == row["time"]
    )
    assert event.gold_lost is None and event.killer_player_slot is None
    assert len(event.source_paths) == 1
    assert len(data.events.hero_deaths) == 65


def test_missing_death_gold_source_uses_explicit_supplement_without_duplicate_events():
    record = primary(9040460429)
    record.data["players"][1]["playbackData"]["goldEvents"] = None
    data = project(record, supplement(record))
    rows = [e for e in data.events.hero_deaths if e.victim_player_slot == 1]
    assert len(rows) == 6
    assert all(e.source_paths[0].source == "opendota" for e in rows)
    assert len(data.events.hero_deaths) == 50


def test_builds_use_observed_inventory_and_timed_upgrades_not_purchase_reconstruction():
    record = primary()
    data = project(record)
    build = data.builds.players[0]
    raw = record.data["players"][0]
    assert len(build.purchase_events) == len(raw["stats"]["itemPurchases"])
    assert len(build.inventory_events) == len(raw["playbackData"]["inventoryEvents"])
    assert (
        build.inventory_events[0].time_seconds == raw["playbackData"]["inventoryEvents"][0]["time"]
    )
    assert build.ability_upgrade_events[0].time_seconds == -89
    assert build.ability_upgrade_events[0].level is None
    assert build.ability_upgrade_events[0].ability.id == 5028
    assert len(build.final_loadout.inventory) == 6


def test_unavailable_supplement_is_explicit_and_never_zero_economy():
    data = project_detail(
        primary(),
        None,
        entities=DetailEntities(DotaCatalogRepository.load_default()),
        units=UnitCatalog.load_default(),
        supplement_error="provider_timeout",
    )
    assert data.economy.radiant_gold_adv is None
    groups = [g for g in data.coverage.groups if g.path == "economy"]
    assert groups[0].status == "unavailable" and groups[0].source_paths == []
    assert "provider_timeout" in groups[0].reason


def test_optional_playback_outage_keeps_minutes_and_recovers_partial_deaths_from_hero_kills():
    record = primary()
    for i, player in enumerate(record.data["players"]):
        player["playbackData"] = None
        record.field_issues.append(f"players[{i}].playbackData")
    extra = OpenDotaGameRecord(
        match_id=record.match_id,
        retrieved_at=record.retrieved_at,
        data=json.loads((FIXTURES / "opendota_8960991322.json").read_text()),
    )
    data = project(record, extra)
    assert len(data.events.hero_deaths) == 64
    assert sum(p.final_stats.deaths for p in data.players) == 65
    assert sum(c.unaccounted_deaths for c in data.coverage.death_counts) == 1
    assert any(
        m.source == "opendota"
        and m.source_value == 1
        and m.source_path
        and 'killed_by["dota_fountain"]' in m.source_path
        for m in data.coverage.missing
    )
    assert all(e.source_paths[0].source == "opendota" for e in data.events.hero_deaths)
    assert all(p.minute_timeline is not None for p in data.players)
    collapse = next(c for c in data.coverage.death_counts if c.player_slot == 132)
    assert (collapse.final_deaths, collapse.known_time_deaths, collapse.unaccounted_deaths) == (
        5,
        4,
        1,
    )
    assert len(data.events.roshan_kills) == 3
    assert sum(e.type == "tormentor_kill" for e in data.events.other_objectives) == 2
    assert any("optional playback" in m.reason for m in data.coverage.missing)


def test_zero_amount_death_is_a_fact_and_unknown_time_death_is_not_dropped():
    record = primary()
    record.data["players"][0]["playbackData"]["goldEvents"][0]["amount"] = 0
    record.data["players"][0]["playbackData"]["goldEvents"][0]["time"] = None
    data = project(record)
    assert len(data.events.hero_deaths) == 65
    counts = data.coverage.death_counts[0]
    assert counts.known_time_deaths == 4 and counts.unknown_time_deaths == 1
    assert counts.unaccounted_deaths == 0
    unknown = next(
        e for e in data.events.hero_deaths if e.victim_player_slot == 0 and e.time_seconds is None
    )
    assert unknown.time_label is None and unknown.gold_lost is None


def test_missing_player_slot_never_receives_unattributed_kills():
    record = primary()
    record.data["players"][0]["playerSlot"] = None
    data = project(record)
    assert data.interactions.players[0].kills_by_target is None


def test_inventory_mapping_gap_points_to_the_real_public_slot_field():
    record = primary()
    record.data["players"][0]["playbackData"]["inventoryEvents"][0]["item0"]["itemId"] = 999999
    data = project(record)
    assert any(
        m.path == "builds.players[0].inventory_events[0].inventory[0].item"
        and m.source_path == "players[0].playbackData.inventoryEvents[0].item0.itemId"
        for m in data.coverage.missing
    )


def test_unavailable_supplement_curves_are_not_advertised_as_an_available_group():
    record = primary(9040460429)
    extra = supplement(record)
    extra.data["radiant_gold_adv"] = None
    extra.data["radiant_xp_adv"] = None
    data = project(record, extra)
    assert next(g for g in data.coverage.groups if g.path == "economy").status == "unavailable"
