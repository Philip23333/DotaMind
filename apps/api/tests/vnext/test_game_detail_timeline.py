from __future__ import annotations

import json
from copy import deepcopy

import pytest

from app.vnext.providers.opendota.detail_projection import project_game_detail
from tests.vnext.test_game_detail_projection import FIXTURE, player, record, source


def test_saved_game_minutes_remain_distinct_from_final_statistics() -> None:
    raw = json.loads(FIXTURE.read_text())
    data = project_game_detail(record(raw))
    p = next(p for p in data.players if p.identity.account_id == 321580662)
    assert len(p.minute_timeline) == 49
    assert p.minute_timeline[10].model_dump() == {
        "time_seconds": 600, "net_worth": 3440, "earned_gold": 2930, "experience": 2383,
        "last_hits": 39, "denies": 2, "kills": 1, "deaths": 0,
    }
    assert p.minute_timeline[-1].time_seconds == 2880
    assert data.match.duration_seconds == 2904
    assert data.economy.time_seconds == raw["players"][0]["times"]
    assert data.economy.radiant_gold_adv[-1] == -29518
    assert data.economy.radiant_gold_adv == raw["radiant_gold_adv"]
    assert "radiant_net_worth_adv" not in data.economy.model_dump()


def test_logs_include_pre_zero_and_equal_time_events_without_reordering_source() -> None:
    p = player(times=[0, 60, 180], kills=8,
               kills_log=[{"time": 60}, {"time": -25}, {"time": 61}],
               deaths_log=[{"time": 60}, {"time": 181}],
               gold_t=[0, 10, 30], xp_t=[0, 20, 60], networth_t=[600, 610, 630],
               lh_t=[0, 1, 3], dn_t=[0, 0, 1])
    raw = source(players=[p])
    before = deepcopy(raw)
    data = project_game_detail(record(raw))
    nodes = data.players[0].minute_timeline
    assert [n.kills for n in nodes] == [1, 2, 3]
    assert [n.deaths for n in nodes] == [0, 1, 1]
    assert [n.time_seconds for n in nodes] == [0, 60, 180]
    assert nodes[-1].kills != data.players[0].final_stats.kills
    assert data.economy.time_seconds is None
    assert raw == before


@pytest.mark.parametrize("log", [None, "bad", [{"time": None}], [{"time": True}]])
def test_unavailable_or_invalid_logs_never_generate_a_zero_curve(log) -> None:
    data = project_game_detail(record(source(players=[player(kills_log=log)])))
    assert [node.kills for node in data.players[0].minute_timeline] == [None, None]
    assert [node.deaths for node in data.players[0].minute_timeline] == [0, 0]
    assert any(m.path == "players[0].minute_timeline.kills" for m in data.coverage.missing)


@pytest.mark.parametrize("axis", [None, [0, 0], [60, 0], [0, True], [0, "60"]])
def test_unknown_or_invalid_player_axis_is_unavailable(axis) -> None:
    data = project_game_detail(record(source(players=[player(times=axis)])))
    assert data.players[0].minute_timeline is None


def test_short_curve_does_not_shift_or_truncate_other_curves() -> None:
    data = project_game_detail(record(source(players=[player(networth_t=[600], xp_t=[0, None])]))
    )
    nodes = data.players[0].minute_timeline
    assert [node.net_worth for node in nodes] == [None, None]
    assert [node.earned_gold for node in nodes] == [0, 100]
    assert [node.experience for node in nodes] == [0, None]
    assert {m.path for m in data.coverage.missing} >= {
        "players[0].minute_timeline.net_worth", "players[0].minute_timeline.experience",
    }


def test_explicit_empty_player_axis_is_not_filled_from_final_stats() -> None:
    p = player(times=[], networth_t=[], gold_t=[], xp_t=[], lh_t=[], dn_t=[], kills=3)
    data = project_game_detail(record(source(players=[p])))
    assert data.players[0].minute_timeline == []
    assert data.economy.time_seconds == []


def test_team_axis_requires_correspondence_not_just_equal_lengths() -> None:
    raw = source(players=[player(), player(times=[0, 120])],
                 radiant_gold_adv=[0, 5], radiant_xp_adv=[0, -10])
    data = project_game_detail(record(raw))
    assert data.economy.time_seconds is None
    assert data.economy.radiant_gold_adv == [0, 5]
    assert data.economy.radiant_xp_adv == [0, -10]
    assert any(m.path == "economy.time_seconds" and m.reason for m in data.coverage.missing)
    raw["players"][1]["times"] = [0, 60]
    aligned = project_game_detail(record(raw))
    assert aligned.economy.time_seconds == [0, 60]
