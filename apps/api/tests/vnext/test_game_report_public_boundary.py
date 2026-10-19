import asyncio

import pytest

from app.vnext.artifacts import ArtifactReader, SessionArtifactStore
from app.vnext.artifacts.query import ArtifactQuerier, ArtifactQueryInput
from app.vnext.artifacts.retrieval import ArtifactPathNotFoundError
from app.vnext.capabilities.game.data import MissingData, TargetValue
from app.vnext.capabilities.game.report import build_game_report
from tests.vnext.test_stratz_detail_projection import primary, project, supplement


def test_report_histories_preserve_governed_facts_without_the_internal_tree():
    record = primary(9040460429)
    data = project(record, supplement(record))
    data.players[0].minute_timeline[0].kills = 91234567
    data.interactions.players[0].damage_by_target.append(TargetValue(value=17))
    before = data.model_dump_json()
    report = build_game_report(data)
    assert "91234567" not in report.model_dump_json()
    for i, player in enumerate(data.players):
        history = report.player_statistics.player_histories[i]
        assert history.identity == player.identity
        assert history.level_events == player.level_events
        assert [n.cumulative_experience for n in history.experience_timeline] == [
            n.cumulative_experience for n in player.minute_timeline
        ]
        assert [n.time_seconds for n in history.experience_timeline] == [
            n.time_seconds for n in player.minute_timeline
        ]
        equipment = report.equipment_and_skills.player_histories[i]
        build = next(b for b in data.builds.players if b.player_slot == player.identity.player_slot)
        for field in (
            "purchase_events",
            "inventory_events",
            "neutral_item_history",
            "ability_upgrade_events",
            "permanent_upgrade_events",
        ):
            assert getattr(equipment, field) == getattr(build, field)
        support = report.support_contributions.player_histories[i]
        assert support.events == player.support.events and support.totals == player.support.totals
        interaction = next(
            p for p in data.interactions.players if p.player_slot == player.identity.player_slot
        )
        relations = report.hero_damage.player_relations[i]
        assert relations.kills_by_target == interaction.kills_by_target
        assert relations.healing_by_target == interaction.healing_by_target
    assert report.hero_damage.player_relations[0].unmatched_damage_by_target == [
        TargetValue(value=17)
    ]
    assert report.events.first_blood == data.events.first_blood
    assert data.model_dump_json() == before


def test_coverage_locations_follow_public_identity_and_sorted_events_not_old_positions():
    record = primary(9040460429)
    data = project(record, supplement(record))
    data.builds.players.reverse()
    build = data.builds.players[0]
    owner_index = next(
        i for i, p in enumerate(data.players) if p.identity.player_slot == build.player_slot
    )
    data.events.roshan_kills.reverse()
    original = data.events.roshan_kills[0]
    data.coverage.missing = [
        MissingData(path="builds.players[0].inventory_events[0].item_neutral", reason="test"),
        MissingData(path="events.roshan_kills[0].actor_unit", reason="test"),
    ]
    original_paths = [p.model_dump() for p in original.source_paths]
    report = build_game_report(data)
    event_index = next(i for i, e in enumerate(report.events.roshan_kills) if e.fact == original)
    assert [m.path for m in report.coverage.missing] == [
        f"report.equipment_and_skills.player_histories[{owner_index}].inventory_events[0].item_neutral",
        f"report.events.roshan_kills[{event_index}].fact.actor_unit",
    ]
    assert [
        p.model_dump() for p in report.events.roshan_kills[event_index].fact.source_paths
    ] == original_paths
    assert report.coverage.conflicts == data.coverage.conflicts
    assert all(g.path.startswith("report.") for g in report.coverage.groups)
    assert data.coverage.missing[0].path.startswith("builds.")


def test_single_artifact_queries_precise_histories_and_has_no_internal_data_route():
    async def run():
        record = primary(9040460429)
        report = build_game_report(project(record, supplement(record)))
        store = SessionArtifactStore()
        document = {"report": report.model_dump(mode="json")}
        ref = await store.put(document)
        querier = ArtifactQuerier(store)
        for expression, fields in (
            (
                "$.report.equipment_and_skills.player_histories[0].inventory_events[*]",
                ["time_seconds", "inventory"],
            ),
            (
                "$.report.player_statistics.player_histories[0].experience_timeline[*]",
                ["time_seconds", "cumulative_experience"],
            ),
            (
                "$.report.support_contributions.player_histories[0].events[*]",
                ["time_seconds", "action"],
            ),
        ):
            result = await querier.query(
                ArtifactQueryInput(ref=ref, expression=expression, fields=fields)
            )
            assert result.returned > 0 and all(not r.missing_fields for r in result.matches)
        missing = await querier.query(
            ArtifactQueryInput(ref=ref, expression="$.data.players[*]", fields=["identity"])
        )
        assert missing.returned == 0
        with pytest.raises(ArtifactPathNotFoundError):
            await ArtifactReader(store).read(ref, "data")
        assert await store.get(ref) == document

    asyncio.run(run())
