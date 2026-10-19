"""Prepared reports bind exact minutes and source facts without prose inference."""

from app.vnext.capabilities.game.report import GameReport, build_game_report
from tests.vnext.test_stratz_detail_projection import primary, project, supplement


def test_report_keeps_all_ten_identities_and_exact_minute_income():
    record = primary(9040460429)
    extra = supplement(record)
    extra.data["players"].reverse()
    data = project(record, extra)
    report = build_game_report(data)
    assert len(report.final_players) == 10 and len(report.damage_matrix) == 100
    minute = next(n for n in report.minute_snapshots if n.time_seconds == 600)
    assert minute.time_label == "10:00" and len(minute.players) == 10
    row = next(p for p in minute.players if p.identity.account_id == 321580662)
    assert row.cumulative_gold_earned == 2930 and row.assists is None
    assert "cumulative_experience" not in row.model_dump()
    assert all(
        p.inventory_observation.time_seconds <= 600
        for p in minute.players
        if p.inventory_observation
    )
    assert GameReport.model_validate_json(report.model_dump_json()) == report


def test_report_does_not_fabricate_source_income_or_zero_missing_deaths():
    record = primary()
    record.data["players"][0]["playbackData"]["goldEvents"] = None
    report = build_game_report(project(record))
    assert len(report.minute_snapshots[20].players) == 10
    row = report.minute_snapshots[20].players[0]
    assert row.cumulative_gold_earned is None and row.known_deaths is None
    assert all(
        c.dealt is None
        for c in report.damage_matrix
        if c.attacker_player_slot == c.target_player_slot
    )


def test_each_normalized_death_is_one_report_fact_and_unknown_time_survives():
    record = primary()
    record.data["players"][0]["playbackData"]["goldEvents"][0]["time"] = None
    data = project(record)
    report = build_game_report(data)
    deaths = [e for e in report.events if e.kind in ("hero_kill", "hero_death")]
    assert len(deaths) == len(data.events.hero_deaths) == 65
    assert any(e.time_seconds is None for e in deaths)


def test_tormentor_reward_requires_unique_exact_shard_evidence_not_just_chat():
    record = primary()
    event = next(e for e in record.data["chatEvents"] if e["type"] == 117)
    owner = next(p for p in record.data["players"] if p["heroId"] == event["fromHeroId"])
    owner["stats"]["matchPlayerBuffEvent"] = [{"time": event["time"], "itemId": 609}]
    data = project(record)
    reward = next(e for e in data.events.other_objectives if e.time_seconds == event["time"])
    assert reward.reward_player_slot == owner["playerSlot"] and reward.reward_item.id == 609
    assert reward.player_slot is None and len(reward.source_paths) == 2
    owner["stats"]["matchPlayerBuffEvent"][0]["time"] += 1
    data = project(record)
    assert all(e.reward_player_slot is None for e in data.events.other_objectives)
