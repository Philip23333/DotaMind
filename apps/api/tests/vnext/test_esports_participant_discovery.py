from __future__ import annotations

import asyncio

from app.vnext.capabilities.esports.match import MatchSearchInput, MatchSearchResult
from app.vnext.capabilities.esports.player import (
    PlayerItem,
    PlayerSearchInput,
    PlayerSearchResult,
    PlayerTeamSummary,
)
from app.vnext.capabilities.esports.team import TeamItem, TeamSearchInput, TeamSearchResult
from app.vnext.composition import VNextServices, build_vnext_registry
from app.vnext.llm.protocol import ToolCall


def test_team_identity_composes_with_match_and_player_search() -> None:
    seen: list[tuple[str, object]] = []

    async def team_search(query: TeamSearchInput) -> TeamSearchResult:
        seen.append(("team", query))
        return TeamSearchResult(
            items=[TeamItem(id=1647, name="Team Liquid", acronym="TL")],
            page=query.page,
            limit=query.limit,
        )

    async def match_search(query: MatchSearchInput) -> MatchSearchResult:
        seen.append(("match", query))
        return MatchSearchResult(items=[], page=query.page, limit=query.limit)

    async def player_search(query: PlayerSearchInput) -> PlayerSearchResult:
        seen.append(("player", query))
        if query.name == "Ame":
            return PlayerSearchResult(
                items=[
                    PlayerItem(
                        id=1669,
                        name="Ame",
                        active=True,
                        current_team=PlayerTeamSummary(
                            id=1647,
                            name="Team Liquid",
                            acronym="TL",
                        ),
                    )
                ],
                page=query.page,
                limit=query.limit,
            )
        return PlayerSearchResult(items=[], page=query.page, limit=query.limit)

    registry = build_vnext_registry(
        VNextServices(
            match_search=match_search,
            team_search=team_search,
            player_search=player_search,
        )
    )

    async def discover() -> list[tuple[str, object]]:
        team = await registry.execute(
            ToolCall(
                id="team",
                name="esports.team.search",
                arguments={"name": "Team Liquid"},
            )
        )
        team_id = team.content["items"][0]["id"]

        await registry.execute(
            ToolCall(
                id="matches",
                name="esports.match.search",
                arguments={"team_id": team_id},
            )
        )
        await registry.execute(
            ToolCall(
                id="roster",
                name="esports.player.search",
                arguments={"team_id": team_id, "active": True},
            )
        )
        player = await registry.execute(
            ToolCall(
                id="player",
                name="esports.player.search",
                arguments={"name": "Ame"},
            )
        )
        current_team_id = player.content["items"][0]["current_team"]["id"]
        await registry.execute(
            ToolCall(
                id="team-by-id",
                name="esports.team.search",
                arguments={"id": current_team_id},
            )
        )
        return seen

    calls = asyncio.run(discover())

    assert [name for name, _ in calls] == ["team", "match", "player", "player", "team"]
    assert calls[0][1].name == "Team Liquid"  # type: ignore[union-attr]
    assert calls[1][1].team_id == 1647  # type: ignore[union-attr]
    assert calls[2][1].team_id == 1647  # type: ignore[union-attr]
    assert calls[2][1].active is True  # type: ignore[union-attr]
    assert calls[3][1].name == "Ame"  # type: ignore[union-attr]
    assert calls[4][1].id == 1647  # type: ignore[union-attr]
