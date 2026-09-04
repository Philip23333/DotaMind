"""Typed model-facing PandaScore esports resource search tools."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from app.vnext.domain.common.models import DomainModel
from app.vnext.providers.pandascore.query import PandaScoreNativeQueryExecutor
from app.vnext.tools.definition import ToolDefinition
from app.vnext.tools.registry import ToolRegistry

from .esports_observation import EsportsSearchObservationBuilder

LifecycleScope = Literal["all", "past", "running", "upcoming"]
MatchType = Literal[
    "all_games_played",
    "best_of",
    "custom",
    "first_to",
    "ow_best_of",
    "red_bull_home_ground",
]
MatchStatus = Literal["canceled", "finished", "not_started", "postponed", "running"]
WinnerType = Literal["Player", "Team"]

LeagueSortField = Literal[
    "id",
    "-id",
    "modified_at",
    "-modified_at",
    "name",
    "-name",
    "slug",
    "-slug",
    "url",
    "-url",
]
MatchSortField = Literal[
    "begin_at",
    "-begin_at",
    "detailed_stats",
    "-detailed_stats",
    "draw",
    "-draw",
    "end_at",
    "-end_at",
    "forfeit",
    "-forfeit",
    "id",
    "-id",
    "match_type",
    "-match_type",
    "modified_at",
    "-modified_at",
    "name",
    "-name",
    "number_of_games",
    "-number_of_games",
    "scheduled_at",
    "-scheduled_at",
    "slug",
    "-slug",
    "status",
    "-status",
    "tournament_id",
    "-tournament_id",
    "winner_id",
    "-winner_id",
    "winner_type",
    "-winner_type",
]


class LeagueFilter(DomainModel):
    id: int | list[int] | None = None
    modified_at: str | list[str] | None = None
    name: str | list[str] | None = None
    slug: str | list[str] | None = None
    url: str | list[str] | None = None


class LeagueTextSearch(DomainModel):
    name: str | None = None
    slug: str | None = None
    url: str | None = None


class LeagueRange(DomainModel):
    id: tuple[int, int] | None = None
    modified_at: tuple[str, str] | None = None
    name: tuple[str, str] | None = None
    slug: tuple[str, str] | None = None
    url: tuple[str, str] | None = None


class LeagueSearchInput(DomainModel):
    filter: LeagueFilter | None = Field(
        default=None,
        description=(
            "Exact league filtering. Legal fields are explicit in this schema; league does not "
            "support a year filter."
        ),
    )
    search: LeagueTextSearch | None = Field(
        default=None,
        description=(
            "Provider text search over league name, slug, or url. Example: "
            "{'name':'The International'}."
        ),
    )
    range: LeagueRange | None = Field(
        default=None,
        description="Native two-value range constraints for the league fields exposed here.",
    )
    sort: list[LeagueSortField] | None = Field(
        default=None,
        description=(
            "Native league sort. Every legal sort value is explicit in this schema; prefix a "
            "field with '-' for descending order."
        ),
    )
    page: int = Field(default=1, ge=1, description="One-based provider result-page number.")
    page_size: int = Field(
        default=10,
        ge=1,
        le=100,
        description="Provider-side rows returned for this call. Keep it small when possible.",
    )


class MatchFilter(DomainModel):
    begin_at: str | list[str] | None = None
    detailed_stats: bool | None = None
    draw: bool | None = None
    end_at: str | list[str] | None = None
    finished: bool | None = Field(
        default=None,
        description=(
            "Exact finished-state filter. scope='past' is not equivalent to finished=true and "
            "can include canceled or other non-finished records."
        ),
    )
    forfeit: bool | None = None
    future: bool | None = None
    id: int | list[int] | None = None
    league_id: int | list[int] | None = Field(
        default=None,
        description="Narrow matches to one or more known league IDs.",
    )
    match_type: MatchType | list[MatchType] | None = None
    modified_at: str | list[str] | None = None
    name: str | list[str] | None = None
    not_started: bool | None = None
    number_of_games: int | list[int] | None = None
    opponent_id: int | str | list[int | str] | None = Field(
        default=None,
        description="Narrow matches to a known opponent/team ID when available.",
    )
    opponents_filled: bool | None = None
    past: bool | None = None
    running: bool | None = None
    scheduled_at: str | list[str] | None = None
    serie_id: int | list[int] | None = Field(
        default=None,
        description="Narrow matches to one or more known serie/edition IDs.",
    )
    slug: str | list[str] | None = None
    status: MatchStatus | list[MatchStatus] | None = None
    tournament_id: int | list[int] | None = Field(
        default=None,
        description="Narrow matches to one or more known tournament/stage IDs.",
    )
    unscheduled: bool | None = None
    videogame: int | str | list[int | str] | None = None
    videogame_title: int | str | list[int | str] | None = None
    videogame_version: str | list[str] | None = None
    winner_id: int | str | list[int | str] | None = None
    winner_type: WinnerType | list[WinnerType] | None = None


class MatchTextSearch(DomainModel):
    match_type: MatchType | None = None
    name: str | None = None
    slug: str | None = None
    status: MatchStatus | None = None
    winner_type: WinnerType | None = None


class MatchRange(DomainModel):
    begin_at: tuple[str, str] | None = None
    detailed_stats: tuple[bool, bool] | None = None
    draw: tuple[bool, bool] | None = None
    end_at: tuple[str, str] | None = None
    forfeit: tuple[bool, bool] | None = None
    id: tuple[int, int] | None = None
    match_type: tuple[MatchType, MatchType] | None = None
    modified_at: tuple[str, str] | None = None
    name: tuple[str, str] | None = None
    number_of_games: tuple[int, int] | None = None
    scheduled_at: tuple[str, str] | None = None
    slug: tuple[str, str] | None = None
    status: tuple[MatchStatus, MatchStatus] | None = None
    tournament_id: tuple[int, int] | None = None
    winner_id: tuple[int | str, int | str] | None = None
    winner_type: tuple[WinnerType, WinnerType] | None = None


class MatchSearchInput(DomainModel):
    scope: LifecycleScope = Field(
        default="all",
        description=(
            "Selects the match lifecycle collection. 'past' does not mean status='finished'; "
            "use filter.finished or filter.status for completed-only results."
        ),
    )
    filter: MatchFilter | None = Field(
        default=None,
        description=(
            "Exact native match filtering. Common narrowing relations are league_id, serie_id, "
            "tournament_id, and opponent_id; prefer the narrowest known ID."
        ),
    )
    search: MatchTextSearch | None = Field(
        default=None,
        description=(
            "Provider text search over the match fields explicitly listed in this schema. It is "
            "not interchangeable with exact filter fields."
        ),
    )
    range: MatchRange | None = Field(
        default=None,
        description="Native two-value range constraints for the match fields exposed here.",
    )
    sort: list[MatchSortField] | None = Field(
        default=None,
        description=(
            "Native match sort. Use 'field' for ascending and '-field' for descending. For "
            "recent finished matches normally use ['-begin_at']; for nearest upcoming matches "
            "use ['begin_at']."
        ),
    )
    page: int = Field(default=1, ge=1, description="One-based provider result-page number.")
    page_size: int = Field(
        default=10,
        ge=1,
        le=100,
        description="Provider-side rows returned for this call. Keep it small when possible.",
    )


class ResourceSearchOutput(DomainModel):
    resource: str
    scope: str
    rows: list[dict]
    has_more: bool | None = None
    truncated: bool = False
    artifact_ref: str | None = None
    returned_rows: int = Field(ge=0)


async def _run_search(
    *,
    resource: str,
    args: DomainModel,
    executor: PandaScoreNativeQueryExecutor,
    observation_builder: EsportsSearchObservationBuilder,
) -> ResourceSearchOutput:
    result = await executor.execute({"resource": resource, **args.model_dump(exclude_none=True)})
    observation = await observation_builder.build(result)
    return ResourceSearchOutput(
        resource=observation.resource,
        scope=observation.scope,
        rows=observation.rows,
        has_more=observation.has_more,
        truncated=observation.truncated,
        artifact_ref=observation.artifact_ref,
        returned_rows=observation.returned_rows,
    )


def build_esports_league_search_tool(
    executor: PandaScoreNativeQueryExecutor,
    observation_builder: EsportsSearchObservationBuilder,
) -> ToolDefinition:
    async def search(args: LeagueSearchInput) -> ResourceSearchOutput:
        return await _run_search(
            resource="league",
            args=args,
            executor=executor,
            observation_builder=observation_builder,
        )

    return ToolDefinition(
        name="esports.league.search",
        description=(
            "Search Dota 2 competition brands/families. 'The International' and 'ESL One' are "
            "leagues; a specific edition such as 'The International 2026' is not. The input "
            "schema directly exposes the supported league query fields, so do not read a manual "
            "merely to discover league fields."
        ),
        input_model=LeagueSearchInput,
        output_model=ResourceSearchOutput,
        handler=search,
    )


def build_esports_match_search_tool(
    executor: PandaScoreNativeQueryExecutor,
    observation_builder: EsportsSearchObservationBuilder,
) -> ToolDefinition:
    async def search(args: MatchSearchInput) -> ResourceSearchOutput:
        return await _run_search(
            resource="match",
            args=args,
            executor=executor,
            observation_builder=observation_builder,
        )

    return ToolDefinition(
        name="esports.match.search",
        description=(
            "Search individual Dota 2 match series between opponents. The input schema directly "
            "exposes supported match relations and query fields. Prefer the narrowest known "
            "league_id, serie_id, or tournament_id, optionally opponent_id. scope='past' is not "
            "the same as finished=true. Exact score claims still require explicit results from "
            "returned rows or their artifact."
        ),
        input_model=MatchSearchInput,
        output_model=ResourceSearchOutput,
        handler=search,
    )


def register_esports_resource_tools(
    registry: ToolRegistry,
    executor: PandaScoreNativeQueryExecutor,
    observation_builder: EsportsSearchObservationBuilder,
) -> None:
    registry.register(build_esports_league_search_tool(executor, observation_builder))
    registry.register(build_esports_match_search_tool(executor, observation_builder))


__all__ = [
    "LeagueFilter",
    "LeagueRange",
    "LeagueSearchInput",
    "LeagueTextSearch",
    "MatchFilter",
    "MatchRange",
    "MatchSearchInput",
    "MatchTextSearch",
    "ResourceSearchOutput",
    "build_esports_league_search_tool",
    "build_esports_match_search_tool",
    "register_esports_resource_tools",
]
