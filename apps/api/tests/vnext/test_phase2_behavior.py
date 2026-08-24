from __future__ import annotations

import asyncio

from tests.vnext.phase2_support import fixture_services


def test_behavior_eval_tournament_status_uses_competition_and_schedule_capabilities() -> None:
    competition_service, _, _, _ = fixture_services()

    async def scenario():
        found = await competition_service.search("The International 2026", year=2026)
        schedule = await competition_service.list_matches(
            found.candidates[0].ref,
            time_scope="all",
            limit=10,
        )
        return found, schedule

    found, schedule = asyncio.run(scenario())
    assert found.status == "unique"
    assert schedule.status == "ok"
    assert schedule.matches
    assert all(match.competition.name == "The International 2026" for match in schedule.matches)


def test_behavior_eval_tournament_schedule_returns_upcoming_facts() -> None:
    competition_service, _, _, _ = fixture_services()

    async def scenario():
        found = await competition_service.search("The International 2026", year=2026)
        return await competition_service.list_matches(
            found.candidates[0].ref,
            time_scope="upcoming",
            limit=5,
        )

    schedule = asyncio.run(scenario())
    assert schedule.status == "ok"
    assert len(schedule.matches) == 1
    assert schedule.matches[0].status == "scheduled"


def test_behavior_eval_match_detail_and_game_follow_up_keep_coverage_boundary() -> None:
    _, match_service, _, _ = fixture_services()

    async def scenario():
        candidates = await match_service.search(
            teams=["Nigma Galaxy", "OG"],
            query="Round 2",
            time_scope="recent",
        )
        detail = await match_service.get_detail(match_ref=candidates.candidates[0].ref)
        follow_up = await match_service.get_detail(game_ref=detail.games[0].ref)
        return candidates, detail, follow_up

    candidates, detail, follow_up = asyncio.run(scenario())
    assert candidates.status == "unique"
    assert detail.status == "available"
    assert follow_up.status == "available"
    assert follow_up.games[0].detail_status == "available"
    assert follow_up.provenance.identity_status == "inferred_cross_source"
