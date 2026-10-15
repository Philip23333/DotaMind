from __future__ import annotations

import json
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.integrations.valve.catalog_repository import DotaCatalogRepository
from app.vnext.capabilities.game.data import FinalStats, GameDetailData
from app.vnext.catalog import UnitCatalog
from app.vnext.providers.opendota.detail_entities import DetailEntities
from app.vnext.providers.opendota.detail_projection import project_game_detail
from app.vnext.providers.opendota.game_detail import OpenDotaGameRecord

FIXTURE = Path(__file__).parent / "fixtures/game_detail/opendota_9040460429.json"


def project(value: OpenDotaGameRecord) -> GameDetailData:
    return project_game_detail(value, entities=DetailEntities(DotaCatalogRepository.load_default()),
                               units=UnitCatalog.load_default())


def record(source: dict) -> OpenDotaGameRecord:
    return OpenDotaGameRecord(
        match_id=source["match_id"], retrieved_at=datetime(2026, 10, 14, tzinfo=UTC), data=source,
    )


def source(**updates) -> dict:
    data = {
        "match_id": 123, "start_time": 1_791_738_028, "duration": 2904,
        "radiant_win": False, "radiant_score": 0, "dire_score": 2,
        "radiant_team": {"team_id": 1, "name": "Radiant", "tag": "not-retained"},
        "dire_team": {"team_id": 2, "name": "Dire"}, "picks_bans": [],
        "players": [], "objectives": [], "radiant_gold_adv": [], "radiant_xp_adv": [],
    }
    data.update(updates)
    return data


def player(**updates) -> dict:
    data = {
        "account_id": 1234, "player_slot": 0, "hero_id": 1, "isRadiant": True,
        "name": "Player", "personaname": None,
        **dict.fromkeys(("kills", "deaths", "assists", "level", "last_hits", "denies",
                         "net_worth", "hero_damage", "tower_damage", "hero_healing"), 0),
        **{f"item_{i}": 0 for i in range(6)}, **{f"backpack_{i}": 0 for i in range(3)},
        "item_neutral": 0, "item_neutral2": 0, "aghanims_scepter": 0,
        "aghanims_shard": 0, "moonshard": 0, "purchase_log": [],
        "ability_upgrades_arr": [], "neutral_item_history": [],
        "times": [0, 60], "gold_t": [0, 100], "networth_t": [600, 700],
        "xp_t": [0, 200], "lh_t": [0, 2], "dn_t": [0, 1],
        "kills_log": [], "deaths_log": [], "buyback_log": [],
        "killed": {}, "damage": {}, "healing": {},
    }
    data.update(updates)
    return data


def test_saved_game_static_facts_and_closed_eight_section_contract() -> None:
    raw = json.loads(FIXTURE.read_text())
    before = deepcopy(raw)
    data = project(record(raw))
    assert set(data.model_dump()) == {
        "match", "draft", "players", "economy", "builds", "events", "interactions", "coverage",
    }
    assert data.match.match_date == "2026-10-12"
    assert data.match.duration_seconds == 2904
    assert data.match.game_winner == "dire"
    assert data.match.teams.radiant.source_team_id == 7119388
    assert data.match.teams.dire.name == "Team Yandex"
    assert data.draft.picks_bans[0].model_dump() == {
        "order": 0, "action": "ban",
        "hero": {"id": 59, "name_zh": "哈斯卡", "name_en": "Huskar"}, "side": "radiant",
    }
    p = next(p for p in data.players if p.identity.account_id == 321580662)
    assert p.identity.side == "radiant"
    assert p.final_stats.model_dump() == {
        "kills": 3, "deaths": 6, "assists": 4, "level": 25, "last_hits": 605,
        "denies": 3, "net_worth": 26064, "hero_damage": 14456,
        "tower_damage": 686, "hero_healing": 0,
    }
    text = data.model_dump_json()
    for excluded in ("damage_targets", "benchmarks", "hero_variant", "pre_game_duration",
                     "permanent_buffs", "gold_per_min", "logo_url"):
        assert f'"{excluded}"' not in text
    assert raw == before
    assert GameDetailData.model_validate(data.model_dump()) == data


@pytest.mark.parametrize(("value", "expected"), [(True, "radiant"), (False, "dire"),
                                                 (None, None), (0, None), (1, None)])
def test_strict_winner_mapping_preserves_false_and_unknown(value, expected) -> None:
    data = project(record(source(radiant_win=value)))
    assert data.match.game_winner == expected
    assert data.match.score.radiant == 0


def test_beijing_date_and_ordered_local_draft_codes() -> None:
    stamp = int(datetime(2026, 10, 11, 16, tzinfo=UTC).timestamp())
    data = project(record(source(start_time=stamp, picks_bans=[
        {"order": 8, "is_pick": False, "hero_id": 1, "team": 1},
        {"order": 2, "is_pick": True, "hero_id": 2, "team": True},
    ])))
    assert data.match.match_date == "2026-10-12"
    assert [p.order for p in data.draft.picks_bans] == [8, 2]
    assert data.draft.picks_bans[0].side == "dire"
    assert data.draft.picks_bans[1].side is None


def test_builds_keep_slots_parts_partial_history_and_skill_order() -> None:
    p = player(item_0=1, item_1=None, moonshard=1, ability_upgrades_arr=[5003, 5004, 730],
               purchase_log=[{"time": -89, "key": "slippers", "charges": 2},
                             {"time": 100, "key": "manta"}],
               neutral_item_history=[{
                   "time": 420, "item_neutral_enhancement": "enhancement_vital",
               }])
    data = project(record(source(players=[p])))
    build = data.builds.players[0]
    assert [x.id if x else None for x in build.final_loadout.inventory] == [1] + [None] * 5
    assert build.final_loadout.backpack == [None, None, None]
    assert build.final_loadout.moonshard == 1
    assert [e.item.id for e in build.purchase_events] == [14, 147]
    assert build.purchase_events[0].time_seconds == -89
    assert build.purchase_events[0].charges == 2
    assert [a.id for a in build.ability_upgrade_sequence] == [5003, 5004, 730]
    assert build.neutral_item_history[0].item is None
    assert build.neutral_item_history[0].enhancement.name_en == "Vital"
    assert data.players[0].final_stats.kills == 0


def test_missing_collections_are_unknown_and_explicit_empty_lists_stay_empty() -> None:
    data = project(record({"match_id": 123}))
    assert data.players is None
    assert data.builds.players is None
    assert data.draft.picks_bans is None
    assert {m.path for m in data.coverage.missing} >= {"players", "draft.picks_bans"}
    empty = project(record(source()))
    assert empty.players == []
    assert empty.builds.players == []
    assert empty.draft.picks_bans == []


def test_identity_is_a_root_failure_and_models_reject_raw_fields_and_coercion() -> None:
    wrong = record(source()).model_copy(update={"match_id": 124})
    with pytest.raises(ValueError, match="identity"):
        project(wrong)
    with pytest.raises(ValidationError):
        FinalStats(kills=True)
    data = project(record(source())).model_dump()
    with pytest.raises(ValidationError):
        GameDetailData.model_validate({**data, "raw": {"match_id": 123}})
