from __future__ import annotations

import asyncio
import json

from app.vnext.composition import build_vnext_registry
from app.vnext.domain.common.models import PlayerRef, TeamRef
from app.vnext.domain.team_player_index import TeamPlayerRefIndex
from app.vnext.llm.protocol import ToolCall
from app.vnext.providers.common import ProviderBatch
from app.vnext.providers.pandascore.models import PandaScoreMatch
from tests.vnext.phase2_support import fixture_services, fixture_vnext_services


def test_team_and_player_services_preserve_source_facts_and_opaque_refs() -> None:
    series_service, match_service, panda, opendota = fixture_services()
    services = fixture_vnext_services(series_service, match_service, panda, opendota)

    team_search = asyncio.run(services.teams.search("  Team   Spirit "))
    assert team_search.status == "unique"
    assert team_search.candidate_count == 1
    team_ref = team_search.candidates[0].ref
    assert isinstance(team_ref, TeamRef)
    assert team_search.candidates[0].location == "RU"
    assert team_search.candidates[0].logo_url is not None

    team_detail = asyncio.run(services.teams.get(team_ref))
    assert team_detail.status == "available"
    assert team_detail.team is not None
    assert len(team_detail.team.players) == 2
    assert isinstance(team_detail.team.players[0].ref, PlayerRef)
    assert team_detail.team.players[0].birthday is not None
    assert team_detail.team.players[0].birth_year is None
    assert team_detail.team.players[1].birthday is None

    player_search = asyncio.run(services.players.search(" Yatoro "))
    assert player_search.status == "ambiguous"
    assert player_search.candidate_count == 2
    yatoro = next(item for item in player_search.candidates if item.name == "Yatoro")
    assert yatoro.current_team is not None
    assert yatoro.current_team.ref == team_ref

    player_detail = asyncio.run(services.players.get(yatoro.ref))
    assert player_detail.status == "available"
    assert player_detail.player is not None
    assert player_detail.player.name == "Yatoro"
    assert player_detail.player.birthday is None
    assert player_detail.player.current_team is not None
    assert player_detail.player.current_team.ref == team_ref

    serialized = json.dumps(
        {
            "team": team_detail.model_dump(mode="json"),
            "player": player_detail.model_dump(mode="json"),
        },
        sort_keys=True,
    )
    for forbidden in ("pandascore_id", "provider_id", "raw_response", "provider_payload"):
        assert forbidden not in serialized


def test_team_search_preserves_ambiguity_when_bounded_result_is_truncated() -> None:
    series_service, match_service, panda, _ = fixture_services()
    services = fixture_vnext_services(series_service, match_service, panda, _)
    original_search = panda.search_teams

    async def truncated_search(*, query: str | None = None, limit: int = 20):
        batch = await original_search(query=query, limit=limit)
        return ProviderBatch(batch.items[:1], batch.fetched_at, has_more=True)

    panda.search_teams = truncated_search  # type: ignore[method-assign]

    result = asyncio.run(services.teams.search("Team Spirit"))

    assert result.status == "ambiguous"
    assert result.candidate_count == 1
    assert result.provenance.identity_status == "ambiguous"
    assert result.provenance.warnings == [
        "provider search was truncated; additional candidates may exist"
    ]


def test_player_search_preserves_ambiguity_when_bounded_result_is_truncated() -> None:
    series_service, match_service, panda, _ = fixture_services()
    services = fixture_vnext_services(series_service, match_service, panda, _)
    original_search = panda.search_players

    async def truncated_search(*, query: str | None = None, limit: int = 20):
        batch = await original_search(query=query, limit=limit)
        return ProviderBatch(batch.items[:1], batch.fetched_at, has_more=True)

    panda.search_players = truncated_search  # type: ignore[method-assign]

    result = asyncio.run(services.players.search("Yatoro"))

    assert result.status == "ambiguous"
    assert result.candidate_count == 1
    assert result.provenance.identity_status == "ambiguous"
    assert result.provenance.warnings == [
        "provider search was truncated; additional candidates may exist"
    ]


def test_shared_index_keeps_match_team_player_identity_consistent_across_tools() -> None:
    series_service, match_service, panda, opendota = fixture_services()
    services = fixture_vnext_services(series_service, match_service, panda, opendota)
    other = panda.matches[0].opponents[1].opponent
    synthetic = PandaScoreMatch.model_validate(
        {
            "id": 99001,
            "name": "Team Spirit exhibition",
            "status": "finished",
            "scheduled_at": "2026-08-20T12:00:00Z",
            "opponents": [
                {
                    "type": "team",
                    "opponent": {
                        "id": 1669,
                        "name": "Team Spirit",
                        "acronym": "TS",
                        "slug": "team-spirit",
                    },
                },
                {"type": "team", "opponent": other.model_dump(by_alias=True)},
            ],
        }
    )
    panda.team_match_pages[1669] = [[synthetic]]

    async def exercise():
        match_result = await services.matches.search(
            teams=["Team Spirit"],
            query="Team Spirit exhibition",
            time_scope="recent",
        )
        team_result = await services.teams.search("Team Spirit")
        player_result = await services.players.search("Yatoro")
        return match_result, team_result, player_result

    match_result, team_result, player_result = asyncio.run(exercise())
    match_team_ref = next(
        team.ref
        for team in match_result.candidates[0].teams
        if team.name == "Team Spirit"
    )
    searched_team_ref = team_result.candidates[0].ref
    yatoro = next(item for item in player_result.candidates if item.name == "Yatoro")
    assert yatoro.current_team is not None
    assert match_team_ref == searched_team_ref == yatoro.current_team.ref

    registry = build_vnext_registry(services)

    async def roundtrip():
        team = await registry.execute(
            ToolCall(
                id="team-detail",
                name="teams.get_detail",
                arguments={"team_ref": {"value": searched_team_ref.value}},
            )
        )
        player = await registry.execute(
            ToolCall(
                id="player-detail",
                name="players.get_detail",
                arguments={"player_ref": {"value": yatoro.ref.value}},
            )
        )
        return team, player

    team, player = asyncio.run(roundtrip())
    assert team.status == player.status == "ok"
    assert team.content["team"]["ref"] == player.content["player"]["current_team"]["ref"]


def test_team_and_player_detail_tools_require_nested_opaque_reference_objects() -> None:
    series_service, match_service, panda, opendota = fixture_services()
    registry = build_vnext_registry(
        fixture_vnext_services(series_service, match_service, panda, opendota)
    )

    async def exercise():
        team = await registry.execute(
            ToolCall(
                id="bad-team",
                name="teams.get_detail",
                arguments={"team_ref": "team:" + "0" * 24},
            )
        )
        player = await registry.execute(
            ToolCall(
                id="bad-player",
                name="players.get_detail",
                arguments={"player_ref": json.dumps({"value": "player:" + "0" * 24})},
            )
        )
        return team, player

    team, player = asyncio.run(exercise())
    assert team.status == player.status == "error"
    assert team.error is not None and team.error.code == "invalid_arguments"
    assert player.error is not None and player.error.code == "invalid_arguments"


def test_unknown_team_and_player_refs_are_typed_not_found_without_provider_calls() -> None:
    series_service, match_service, panda, opendota = fixture_services()
    services = fixture_vnext_services(series_service, match_service, panda, opendota)

    team_result = asyncio.run(services.teams.get(TeamRef(value="team:" + "f" * 24)))
    player_result = asyncio.run(services.players.get(PlayerRef(value="player:" + "f" * 24)))

    assert team_result.status == player_result.status == "not_found"
    assert panda.team_get_calls == []
    assert panda.player_get_calls == []


def test_team_player_index_uses_distinct_deterministic_namespaces() -> None:
    index = TeamPlayerRefIndex()
    team = index.remember_team(1669)
    player = index.remember_player(30258)

    assert team.value.startswith("team:")
    assert player.value.startswith("player:")
    assert index.team_provider_id(team) == 1669
    assert index.player_provider_id(player) == 30258
