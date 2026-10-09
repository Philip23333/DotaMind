"""Attach verified local display references to explicit Team result fields."""

from __future__ import annotations

from app.vnext.capabilities.esports.dtos import (
    MatchDTO,
    PlayerDTO,
    TeamDTO,
    TeamRefDTO,
    TournamentDTO,
)
from app.vnext.capabilities.esports.match import MatchSearchResult
from app.vnext.capabilities.esports.player import PlayerSearchResult
from app.vnext.capabilities.esports.series import SeriesTeamsResult
from app.vnext.capabilities.esports.team import TeamSearchResult
from app.vnext.capabilities.esports.tournament import TournamentSearchResult
from app.vnext.entity_display import (
    EntityDisplayDirectory,
    EntityIdentity,
    make_display_ref,
)


def enrich_team_search_result(
    result: TeamSearchResult,
    directory: EntityDisplayDirectory,
) -> TeamSearchResult:
    refs = _resolve_team_refs(result.items, directory)
    return result.model_copy(
        update={"items": [_copy_team(team, refs) for team in result.items]}
    )


def enrich_series_teams_result(
    result: SeriesTeamsResult,
    directory: EntityDisplayDirectory,
) -> SeriesTeamsResult:
    refs = _resolve_team_refs(result.items, directory)
    return result.model_copy(
        update={"items": [_copy_team(team, refs) for team in result.items]}
    )


def enrich_tournament_search_result(
    result: TournamentSearchResult,
    directory: EntityDisplayDirectory,
) -> TournamentSearchResult:
    teams = [
        participant.team
        for tournament in result.items
        for participant in tournament.participants
    ]
    refs = _resolve_team_refs(teams, directory)
    items: list[TournamentDTO] = []
    for tournament in result.items:
        participants = [
            participant.model_copy(
                update={"team": _copy_team(participant.team, refs)}
            )
            for participant in tournament.participants
        ]
        items.append(tournament.model_copy(update={"participants": participants}))
    return result.model_copy(update={"items": items})


def enrich_match_search_result(
    result: MatchSearchResult,
    directory: EntityDisplayDirectory,
) -> MatchSearchResult:
    teams = [
        participant.team
        for match in result.items
        for participant in match.participants
    ]
    refs = _resolve_team_refs(teams, directory)
    items: list[MatchDTO] = []
    for match in result.items:
        participants = [
            participant.model_copy(
                update={"team": _copy_team(participant.team, refs)}
            )
            for participant in match.participants
        ]
        items.append(match.model_copy(update={"participants": participants}))
    return result.model_copy(update={"items": items})


def enrich_player_search_result(
    result: PlayerSearchResult,
    directory: EntityDisplayDirectory,
) -> PlayerSearchResult:
    teams = [player.current_team for player in result.items if player.current_team]
    refs = _resolve_team_refs(teams, directory)
    items: list[PlayerDTO] = []
    for player in result.items:
        current_team = player.current_team
        items.append(
            player.model_copy(
                update={
                    "current_team": (
                        _copy_team(current_team, refs) if current_team is not None else None
                    )
                }
            )
        )
    return result.model_copy(update={"items": items})


def _resolve_team_refs(
    teams: list[TeamDTO | TeamRefDTO],
    directory: EntityDisplayDirectory,
) -> dict[int, str]:
    refs_by_id: dict[int, str] = {}
    for team in teams:
        team_id = team.id
        if type(team_id) is not int or team_id <= 0 or team_id in refs_by_id:
            continue
        refs_by_id[team_id] = make_display_ref(
            EntityIdentity(source="pandascore", kind="team", entity_id=team_id)
        )

    if not refs_by_id:
        return {}
    resolved = directory.resolve_many(refs_by_id.values())
    return {
        team_id: display_ref
        for team_id, display_ref in refs_by_id.items()
        if display_ref in resolved
    }


def _copy_team(
    team: TeamDTO | TeamRefDTO,
    refs_by_id: dict[int, str],
) -> TeamDTO | TeamRefDTO:
    return team.model_copy(update={"display_ref": refs_by_id.get(team.id)})


__all__ = [
    "enrich_match_search_result",
    "enrich_player_search_result",
    "enrich_series_teams_result",
    "enrich_team_search_result",
    "enrich_tournament_search_result",
]
