"""Thin agent-visible match tool definitions."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from app.vnext.artifacts import GameSummaryArtifactProducer
from app.vnext.domain.common.models import CompetitionRef, DomainModel, GameRef, MatchRef
from app.vnext.domain.matches.models import MatchDetail, MatchSearchResult
from app.vnext.domain.matches.service import MatchService
from app.vnext.tools.definition import ToolDefinition
from app.vnext.tools.registry import ToolRegistry


class MatchSearchInput(DomainModel):
    query: str | None = None
    teams: list[str] = Field(default_factory=list, max_length=2)
    competition: CompetitionRef | None = Field(
        default=None,
        description=(
            "Optional CompetitionRef object returned by competitions.search. This field is "
            "named competition, not competition_ref. Use: {\"competition\":{\"value\":"
            "\"competition:0123456789abcdef01234567\"}}."
        ),
    )
    time_scope: Literal["upcoming", "recent", "running", "all"] = "all"
    limit: int = Field(default=10, ge=1, le=50)


class MatchGetDetailInput(DomainModel):
    match_ref: MatchRef | None = Field(
        default=None,
        description=(
            "MatchRef object returned by matches.search. Pass the whole object unchanged: "
            "{\"match_ref\":{\"value\":\"match:0123456789abcdef01234567\"}}. "
            "Provide exactly one of match_ref or game_ref."
        ),
    )
    game_ref: GameRef | None = Field(
        default=None,
        description=(
            "GameRef object returned by matches.get_detail. Pass the whole object unchanged: "
            "{\"game_ref\":{\"value\":"
            "\"game:0123456789abcdef01234567\"}}. Provide exactly one of match_ref "
            "or game_ref."
        ),
    )

    @model_validator(mode="after")
    def require_one_reference(self) -> MatchGetDetailInput:
        if (self.match_ref is None) == (self.game_ref is None):
            raise ValueError("provide exactly one match_ref or game_ref")
        return self


def register_match_tools(
    registry: ToolRegistry,
    service: MatchService,
    game_summary_producer: GameSummaryArtifactProducer,
) -> None:
    async def search(args: MatchSearchInput) -> MatchSearchResult:
        return await service.search(
            query=args.query,
            teams=args.teams,
            competition=args.competition,
            time_scope=args.time_scope,
            limit=args.limit,
        )

    async def get_detail(args: MatchGetDetailInput) -> MatchDetail:
        detail = await service.get_detail(match_ref=args.match_ref, game_ref=args.game_ref)
        for game in detail.games:
            if game.valve_match_id is not None:
                await game_summary_producer.produce(game.valve_match_id)
        return detail

    registry.register(
        ToolDefinition(
            name="matches.search",
            description=(
                "Find professional Dota 2 series by teams, competition, query, or time scope. "
                "When filtering by competition, pass the CompetitionRef object returned by "
                "competitions.search. Returns ordered candidates without guessing among ambiguity."
            ),
            input_model=MatchSearchInput,
            output_model=MatchSearchResult,
            handler=search,
            parallel_safe=True,
        )
    )
    registry.register(
        ToolDefinition(
            name="matches.get_detail",
            description=(
                "Return normalized series facts and available game detail for one match or game. "
                "Resolved games include their canonical Valve match ID and a stored local "
                "GameSummary artifact. Cross-source mapping and coverage limits remain explicit."
            ),
            input_model=MatchGetDetailInput,
            output_model=MatchDetail,
            handler=get_detail,
            read_only=False,
            parallel_safe=True,
        )
    )


__all__ = ["MatchGetDetailInput", "MatchSearchInput", "register_match_tools"]
