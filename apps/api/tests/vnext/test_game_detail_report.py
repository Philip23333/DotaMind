"""Prepared reports bind exact minutes and source facts without prose inference."""

import asyncio

from app.vnext.artifacts import SessionArtifactStore
from app.vnext.artifacts.query import ArtifactQuerier, ArtifactQueryInput
from app.vnext.capabilities.game.data import (
    EntityData,
    InventoryEvent,
    InventorySlot,
    LevelEvent,
    NeutralItemEvent,
)
from app.vnext.capabilities.game.report import GameReport, build_game_report
from tests.vnext.test_stratz_detail_projection import primary, project, supplement


def test_report_keeps_all_ten_identities_and_exact_minute_income():
    record = primary(9040460429)
    extra = supplement(record)
    extra.data["players"].reverse()
    data = project(record, extra)
    report = build_game_report(data)
    assert len(report.player_statistics.final_players) == 10
    assert len(report.hero_damage.matrix) == 100
    minute = next(n for n in report.player_statistics.minute_snapshots if n.time_seconds == 600)
    assert minute.time_label == "10:00" and len(minute.players) == 10
    row = next(p for p in minute.players if p.identity.account_id == 321580662)
    assert row.cumulative_gold_earned == 2930 and row.assists is None
    assert "cumulative_experience" not in row.model_dump()
    assert all(
        "time_seconds" not in p.inventory_observation.model_dump()
        for p in report.equipment_and_skills.minute_snapshots[10].players
        if p.inventory_observation
    )
    assert GameReport.model_validate_json(report.model_dump_json()) == report


def test_minute_states_have_only_the_snapshot_time_and_never_select_future_events():
    data = project(primary(9040460429))
    player = data.players[0]
    build = next(b for b in data.builds.players if b.player_slot == player.identity.player_slot)
    player.level_events = [
        LevelEvent(time_seconds=1668, level=21),
        LevelEvent(time_seconds=1822, level=22),
    ]
    build.inventory_events = [
        InventoryEvent(
            time_seconds=t,
            inventory=[InventorySlot(item=EntityData(id=item))] + [None] * 5,
            backpack=[None] * 3,
        )
        for t, item in [(1738, 108), (1822, 1)]
    ]
    build.neutral_item_history = [
        NeutralItemEvent(time_seconds=t, item=EntityData(id=item))
        for t, item in [(1566, 2), (1822, 3)]
    ]
    before = data.model_dump(mode="json")
    report = build_game_report(data)
    stats_snapshot = report.player_statistics.minute_snapshots[30]
    assert stats_snapshot.time_label == "30:00" and stats_snapshot.time_seconds == 1800
    assert next(p for p in stats_snapshot.players if p.identity == player.identity).level == 21
    snapshot = report.equipment_and_skills.minute_snapshots[30]
    row = next(p for p in snapshot.players if p.identity == player.identity)
    assert row.inventory_observation.inventory[0].item.id == 108
    assert row.neutral_observation.item.id == 2

    def assert_no_times(value):
        if isinstance(value, dict):
            assert not any("time" in key or "observed_at" in key for key in value)
            for child in value.values():
                assert_no_times(child)
        elif isinstance(value, list):
            for child in value:
                assert_no_times(child)

    for module in (
        report.player_statistics,
        report.equipment_and_skills,
        report.support_contributions,
    ):
        for minute in module.minute_snapshots:
            assert_no_times(minute.model_dump(mode="json")["players"])
    assert data.model_dump(mode="json") == before
    assert build.inventory_events[0].time_label == "28:58"
    assert player.level_events[0].time_label == "27:48"
    assert report.schema_version == 4
    assert GameReport.model_validate_json(report.model_dump_json()) == report


def test_report_does_not_fabricate_source_income_or_zero_missing_deaths():
    record = primary()
    record.data["players"][0]["playbackData"]["goldEvents"] = None
    report = build_game_report(project(record))
    assert len(report.player_statistics.minute_snapshots[20].players) == 10
    row = report.player_statistics.minute_snapshots[20].players[0]
    assert row.cumulative_gold_earned is None and row.known_deaths is None
    assert all(
        c.dealt is None
        for c in report.hero_damage.matrix
        if c.attacker_player_slot == c.target_player_slot
    )


def test_each_normalized_death_is_one_report_fact_and_unknown_time_survives():
    record = primary()
    record.data["players"][0]["playbackData"]["goldEvents"][0]["time"] = None
    data = project(record)
    report = build_game_report(data)
    deaths = report.events.hero_kills_and_deaths
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


def test_default_tables_do_not_repeat_long_support_evidence_or_full_skill_logs():
    import json

    record = primary(9040460429)
    for player in record.data["players"]:
        player["playbackData"]["itemUsedEvents"] = [{"time": t, "itemId": 40} for t in range(400)]
    report = build_game_report(project(record, supplement(record)))

    def encoded(value):
        return len(json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode())

    for module in (
        report.player_statistics,
        report.equipment_and_skills,
        report.support_contributions,
    ):
        assert max(encoded(s.model_dump(mode="json")) for s in module.minute_snapshots) < 35840
        assert encoded([p.model_dump(mode="json") for p in module.final_players]) < 35840
    assert report.equipment_and_skills.final_players[0].ability_upgrade_events_path.startswith(
        "$.report.equipment_and_skills.player_histories["
    )


def test_topic_tables_keep_exact_identity_and_same_artifact_history_paths():
    record = primary(9040460429)
    data = project(record, supplement(record))
    data.builds.players.reverse()
    before = data.model_dump(mode="json")
    report = build_game_report(data)
    modules = (report.player_statistics, report.equipment_and_skills, report.support_contributions)
    for module in modules:
        assert [row.identity for row in module.final_players] == [p.identity for p in data.players]
        assert [s.time_seconds for s in module.minute_snapshots] == list(range(0, 2905, 60))
        assert all(
            [row.identity for row in s.players] == [p.identity for p in data.players]
            for s in module.minute_snapshots
        )
    stats = report.player_statistics.minute_snapshots[10].players[0].model_dump()
    equipment = report.equipment_and_skills.minute_snapshots[10].players[0].model_dump()
    support = report.support_contributions.minute_snapshots[10].players[0].model_dump()
    assert "inventory_observation" not in stats and "support_known_counts" not in stats
    assert "cumulative_gold_earned" not in equipment and "support_known_counts" not in equipment
    assert set(support) == {"identity", "support_known_counts"}
    for public_index, row in enumerate(report.equipment_and_skills.final_players):
        index = next(
            i
            for i, b in enumerate(data.builds.players)
            if b.player_slot == row.identity.player_slot
        )
        assert row.final_loadout == data.builds.players[index].final_loadout
        assert row.purchase_events_path == (
            f"$.report.equipment_and_skills.player_histories[{public_index}].purchase_events"
        )
        assert row.ability_upgrade_events_path == (
            f"$.report.equipment_and_skills.player_histories[{public_index}].ability_upgrade_events"
        )
    for index, row in enumerate(report.support_contributions.final_players):
        assert row.events_path == (
            f"$.report.support_contributions.player_histories[{index}].events"
            if data.players[index].support
            else None
        )
    assert report.player_statistics.team_economy_timeline == data.economy.minute_timeline
    assert report.overview.match == data.match and report.overview.draft == data.draft
    assert data.model_dump(mode="json") == before


def test_event_tables_preserve_each_source_fact_once_within_its_category():
    record = primary(9040460429)
    data = project(record, supplement(record))
    report = build_game_report(data)
    for name in (
        "hero_kills_and_deaths",
        "buybacks",
        "building_destructions",
        "roshan_kills",
        "aegis_pickups",
        "other_objectives",
    ):
        rows = getattr(report.events, name)
        source = getattr(data.events, "hero_deaths" if name == "hero_kills_and_deaths" else name)
        assert len(rows) == len(source or [])
        assert sorted(r.fact.model_dump_json() for r in rows) == sorted(
            r.model_dump_json() for r in source or []
        )
        assert rows == sorted(rows, key=lambda e: (e.time_seconds is None, e.time_seconds or 0))
    assert GameReport.model_validate_json(report.model_dump_json()) == report


def test_all_topic_tables_are_queryable_through_one_artifact_reference():
    async def run():
        record = primary(9040460429)
        data = project(record, supplement(record))
        report = build_game_report(data)
        document = {"report": report.model_dump(mode="json")}
        store = SessionArtifactStore()
        ref = await store.put(document)
        querier = ArtifactQuerier(store)
        for name in ("player_statistics", "equipment_and_skills", "support_contributions"):
            result = await querier.query(
                ArtifactQueryInput(
                    ref=ref,
                    expression=f"$.report.{name}.minute_snapshots[?@.time_seconds == 600]",
                    fields=["time_seconds", "time_label", "players"],
                )
            )
            assert result.returned == 1 and result.next_offset is None
            assert result.matches[0].value["time_label"] == "10:00"
            assert len(result.matches[0].value["players"]) == 10
            final = await querier.query(
                ArtifactQueryInput(
                    ref=ref, expression=f"$.report.{name}.final_players[*]", fields=["identity"]
                )
            )
            assert final.returned == 10
        for expression, fields in (
            ("$.report.overview", ["match", "draft"]),
            ("$.report.hero_damage.matrix[*]", ["attacker_player_slot", "target_player_slot"]),
            ("$.report.events.roshan_kills[*]", ["time_seconds", "kind", "fact"]),
        ):
            result = await querier.query(
                ArtifactQueryInput(ref=ref, expression=expression, fields=fields)
            )
            assert result.returned > 0
            assert all(not row.missing_fields for row in result.matches)
        path = report.equipment_and_skills.final_players[0].ability_upgrade_events_path
        skills = await querier.query(
            ArtifactQueryInput(
                ref=ref, expression=f"{path}[*]", fields=["time_seconds", "ability", "level"]
            )
        )
        assert skills.returned > 0
        assert await store.get(ref) == document

    asyncio.run(run())
