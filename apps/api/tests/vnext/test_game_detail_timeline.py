from __future__ import annotations

import json
from copy import deepcopy

import pytest

from tests.vnext.test_game_detail_projection import FIXTURE, player, project, record, source


def test_saved_game_minutes_remain_distinct_from_final_statistics() -> None:
    raw = json.loads(FIXTURE.read_text())
    data = project(record(raw))
    p = next(p for p in data.players if p.identity.account_id == 321580662)
    assert len(p.minute_timeline) == 49
    assert p.minute_timeline[10].model_dump() == {
        "time_seconds": 600,
        "time_label": "10:00",
        "cumulative_gold_earned": 2930,
        "cumulative_experience": 2383,
        "last_hits": 39,
        "denies": 2,
        "kills": 1,
        "known_deaths": 0,
        "assists": None,
        "level": None,
    }
    assert p.minute_timeline[-1].time_seconds == 2880
    assert data.match.duration_seconds == 2904
    assert [n.time_seconds for n in data.economy.minute_timeline] == raw["players"][0]["times"]
    assert data.economy.minute_timeline[-1].radiant_gold_adv == -29518
    assert [n.radiant_gold_adv for n in data.economy.minute_timeline] == raw["radiant_gold_adv"]
    assert "radiant_net_worth_adv" not in data.economy.model_dump()


def test_logs_include_pre_zero_and_equal_time_events_without_reordering_source() -> None:
    p = player(
        times=[0, 60, 180],
        kills=8,
        kills_log=[{"time": 60}, {"time": -25}, {"time": 61}],
        deaths_log=[{"time": 60}, {"time": 181}],
        gold_t=[0, 10, 30],
        xp_t=[0, 20, 60],
        networth_t=[600, 610, 630],
        lh_t=[0, 1, 3],
        dn_t=[0, 0, 1],
    )
    raw = source(players=[p])
    before = deepcopy(raw)
    data = project(record(raw))
    nodes = data.players[0].minute_timeline
    assert [n.kills for n in nodes] == [1, 2, 3]
    assert [n.known_deaths for n in nodes] == [0, 1, 1]
    assert [n.time_seconds for n in nodes] == [0, 60, 180]
    assert nodes[-1].kills != data.players[0].final_stats.kills
    assert data.economy.minute_timeline is None
    assert raw == before


@pytest.mark.parametrize("log", [None, "bad", [{"time": None}], [{"time": True}]])
def test_unavailable_or_invalid_logs_never_generate_a_zero_curve(log) -> None:
    data = project(record(source(players=[player(kills_log=log)])))
    assert [node.kills for node in data.players[0].minute_timeline] == [None, None]
    assert [node.known_deaths for node in data.players[0].minute_timeline] == [0, 0]
    assert any(m.path == "players[0].minute_timeline.kills" for m in data.coverage.missing)


@pytest.mark.parametrize("axis", [None, [0, 0], [60, 0], [0, True], [0, "60"]])
def test_unknown_or_invalid_player_axis_is_unavailable(axis) -> None:
    data = project(record(source(players=[player(times=axis)])))
    assert data.players[0].minute_timeline is None


def test_short_curve_does_not_shift_or_truncate_other_curves() -> None:
    data = project(record(source(players=[player(gold_t=[600], xp_t=[0, None])])))
    nodes = data.players[0].minute_timeline
    assert [node.cumulative_gold_earned for node in nodes] == [None, None]
    assert [node.cumulative_experience for node in nodes] == [0, None]
    assert {m.path for m in data.coverage.missing} >= {
        "players[0].minute_timeline.cumulative_gold_earned",
        "players[0].minute_timeline.cumulative_experience",
    }


def test_explicit_empty_player_axis_is_not_filled_from_final_stats() -> None:
    p = player(times=[], networth_t=[], gold_t=[], xp_t=[], lh_t=[], dn_t=[], kills=3)
    data = project(record(source(players=[p])))
    assert data.players[0].minute_timeline == []
    assert data.economy.minute_timeline == []


def test_team_axis_requires_correspondence_not_just_equal_lengths() -> None:
    raw = source(
        players=[player(), player(times=[0, 120])], radiant_gold_adv=[0, 5], radiant_xp_adv=[0, -10]
    )
    data = project(record(raw))
    assert data.economy.model_dump() == {"minute_timeline": None}
    assert any(m.path == "economy.minute_timeline" and m.reason for m in data.coverage.missing)
    raw["players"][1]["times"] = [0, 60]
    aligned = project(record(raw))
    assert [n.model_dump() for n in aligned.economy.minute_timeline] == [
        {"time_seconds": 0, "time_label": "00:00", "radiant_gold_adv": 0, "radiant_xp_adv": 0},
        {"time_seconds": 60, "time_label": "01:00", "radiant_gold_adv": 5, "radiant_xp_adv": -10},
    ]


@pytest.mark.parametrize("gold", [None, [367], [367, 735, 999], [367, True]])
def test_team_metric_gaps_do_not_shift_time_or_discard_valid_experience(gold) -> None:
    raw = source(players=[player()], radiant_gold_adv=gold, radiant_xp_adv=[100, -81])
    original = deepcopy(raw)
    data = project(record(raw))
    nodes = data.economy.minute_timeline
    assert [n.time_seconds for n in nodes] == [0, 60]
    assert [n.radiant_xp_adv for n in nodes] == [100, -81]
    expected_gold = [367, None] if gold == [367, True] else [None, None]
    assert [n.radiant_gold_adv for n in nodes] == expected_gold
    assert any(m.path == "economy.minute_timeline.radiant_gold_adv" for m in data.coverage.missing)
    assert raw == original


def test_team_axis_is_not_synthesized_from_series_lengths_or_missing_players() -> None:
    data = project(record(source(players=[], radiant_gold_adv=[0, 1], radiant_xp_adv=[0, 2])))
    assert data.economy.minute_timeline is None


def test_all_unusable_team_metrics_do_not_create_empty_fact_rows() -> None:
    data = project(record(source(players=[player()], radiant_gold_adv=None, radiant_xp_adv=[1])))
    assert data.economy.minute_timeline is None


def test_unknown_time_deaths_keep_final_total_and_do_not_erase_known_curve():
    raw = source(players=[player(deaths=3, deaths_log=[{"time": None}, {"time": 60}])])
    data = project(record(raw))
    assert data.players[0].final_stats.deaths == 3
    assert [n.known_deaths for n in data.players[0].minute_timeline] == [0, 1]
    counts = data.coverage.death_counts[0]
    assert (counts.known_time_deaths, counts.unknown_time_deaths, counts.unaccounted_deaths) == (
        1,
        1,
        1,
    )
    assert len(data.events.hero_deaths) == 2
    assert data.events.hero_deaths[0].source_paths[0].source == "opendota"


def test_removed_net_worth_is_neither_public_data_nor_a_coverage_gap():
    data = project(record(source(players=[player(net_worth=1000, networth_t=None)])))
    stats = data.players[0].final_stats.model_dump()
    assert "net_worth" not in stats and stats["earned_gold_net_worth_gap"] is None
    assert all("net_worth" not in n.model_dump() for n in data.players[0].minute_timeline)
    assert not any(m.path.endswith(".net_worth") for m in data.coverage.missing)


def test_excess_death_evidence_is_not_forced_to_match_final_count():
    data = project(record(source(players=[player(deaths=0, deaths_log=[{"time": 60}])])))
    assert data.coverage.death_counts[0].unaccounted_deaths is None
    assert data.coverage.death_counts[0].known_time_deaths == 1
    assert any("exceeds final" in m.reason for m in data.coverage.missing)
