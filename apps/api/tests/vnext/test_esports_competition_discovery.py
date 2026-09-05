from __future__ import annotations

import asyncio

from app.vnext.capabilities.esports.league import (
    LeagueItem,
    LeagueSearchInput,
    LeagueSearchResult,
)
from app.vnext.capabilities.esports.match import MatchSearchInput, MatchSearchResult
from app.vnext.capabilities.esports.series import (
    SeriesItem,
    SeriesSearchInput,
    SeriesSearchResult,
)
from app.vnext.capabilities.esports.tournament import (
    TournamentItem,
    TournamentSearchInput,
    TournamentSearchResult,
)
from app.vnext.composition import VNextServices, build_vnext_registry
from app.vnext.llm.protocol import ToolCall


def test_esports_competition_discovery_contract_is_composable() -> None:
    seen: list[tuple[str, object]] = []

    async def league_search(query: LeagueSearchInput) -> LeagueSearchResult:
        seen.append(("league", query))
        return LeagueSearchResult(
            items=[LeagueItem(id=4106, name="The International")],
            page=query.page,
            limit=query.limit,
        )

    async def series_search(query: SeriesSearchInput) -> SeriesSearchResult:
        seen.append(("series", query))
        return SeriesSearchResult(
            items=[SeriesItem(id=10828, full_name="2026", year=2026)],
            page=query.page,
            limit=query.limit,
        )

    async def tournament_search(query: TournamentSearchInput) -> TournamentSearchResult:
        seen.append(("tournament", query))
        return TournamentSearchResult(
            items=[TournamentItem(id=21545, name="Group Stage", series_id=query.series_id)],
            page=query.page,
            limit=query.limit,
        )

    async def match_search(query: MatchSearchInput) -> MatchSearchResult:
        seen.append(("match", query))
        return MatchSearchResult(items=[], page=query.page, limit=query.limit)

    registry = build_vnext_registry(
        VNextServices(
            league_search=league_search,
            series_search=series_search,
            tournament_search=tournament_search,
            match_search=match_search,
        )
    )

    async def discover() -> list[tuple[str, object]]:
        league = await registry.execute(
            ToolCall(
                id="league",
                name="esports.league.search",
                arguments={"name": "The International"},
            )
        )
        league_id = league.content["items"][0]["id"]

        series = await registry.execute(
            ToolCall(
                id="series",
                name="esports.series.search",
                arguments={"league_id": league_id, "year": 2026},
            )
        )
        series_id = series.content["items"][0]["id"]

        tournament = await registry.execute(
            ToolCall(
                id="tournament",
                name="esports.tournament.search",
                arguments={"series_id": series_id, "name": "Group Stage"},
            )
        )
        tournament_id = tournament.content["items"][0]["id"]

        await registry.execute(
            ToolCall(
                id="match",
                name="esports.match.search",
                arguments={"tournament_id": tournament_id},
            )
        )
        return seen

    calls = asyncio.run(discover())

    assert [name for name, _ in calls] == ["league", "series", "tournament", "match"]
    assert calls[0][1].name == "The International"  # type: ignore[union-attr]
    assert calls[1][1].league_id == 4106  # type: ignore[union-attr]
    assert calls[1][1].year == 2026  # type: ignore[union-attr]
    assert calls[2][1].series_id == 10828  # type: ignore[union-attr]
    assert calls[3][1].tournament_id == 21545  # type: ignore[union-attr]
