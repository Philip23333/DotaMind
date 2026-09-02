"""Thin agent-visible match tool definitions."""

from __future__ import annotations

from app.vnext.artifacts import ArtifactScopeRef, GameSummaryArtifactProducer
from app.vnext.domain.common.models import DomainModel
from app.vnext.domain.construction import GameEventContext
from app.vnext.domain.matches.models import MatchDetail
from app.vnext.domain.matches.service import MatchService
from app.vnext.domain.source import SourceLocator
from app.vnext.tools.definition import ToolDefinition
from app.vnext.tools.registry import ToolRegistry


class MatchGetDetailInput(DomainModel):
    locator: SourceLocator


def register_match_tools(
    registry: ToolRegistry,
    service: MatchService,
    game_summary_producer: GameSummaryArtifactProducer,
) -> None:
    async def get_detail(args: MatchGetDetailInput) -> MatchDetail:
        detail = await service.get_detail(locator=args.locator)
        for game in detail.games:
            if game.valve_match_id is not None:
                await game_summary_producer.produce(
                    game.valve_match_id,
                    event_context=_event_context(detail.match, game),
                    scope_refs=_scope_refs(detail.match),
                )
        return detail

    registry.register(
        ToolDefinition(
            name="matches.get_detail",
            description=(
                "Return normalized series facts and available game detail for a match or game "
                "SourceLocator. "
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


def _event_context(match: object | None, game: object) -> GameEventContext | None:
    if match is None:
        return None
    league = getattr(match, "league", None)
    series = getattr(match, "series", None)
    tournament = getattr(match, "tournament", None)
    return GameEventContext(
        league_name=getattr(league, "name", None),
        series_name=getattr(series, "name", None),
        series_year=getattr(series, "year", None),
        series_season=getattr(series, "season", None),
        tournament_name=getattr(tournament, "name", None),
        match_name=getattr(match, "name", None),
        match_number_of_games=getattr(match, "games_count", None),
        game_position=getattr(game, "position", None),
    )


def _scope_refs(match: object | None) -> list[ArtifactScopeRef]:
    if match is None:
        return []
    scopes: list[ArtifactScopeRef] = []
    for field_name in ("league", "series", "tournament"):
        item = getattr(match, field_name, None)
        ref = getattr(item, "ref", None)
        value = getattr(ref, "value", None)
        if isinstance(value, str):
            scopes.append(ArtifactScopeRef(value=value))
    match_ref = getattr(getattr(match, "ref", None), "value", None)
    if isinstance(match_ref, str):
        scopes.append(ArtifactScopeRef(value=match_ref))
    return scopes


__all__ = ["MatchGetDetailInput", "register_match_tools"]
