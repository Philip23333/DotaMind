"""Canonical GameSummaryArtifact schema version 5 with esports event context."""

from typing import Literal

from pydantic import Field

from .game_summary_v4 import (
    Draft,
    GameInfo,
    PlayerGameSummary,
    Teams,
    _GameSummaryModel,
)


class EventLeague(_GameSummaryModel):
    name: str | None = None


class EventSeries(_GameSummaryModel):
    name: str | None = None
    year: int | None = None
    season: str | None = None


class EventTournament(_GameSummaryModel):
    name: str | None = None


class EventMatch(_GameSummaryModel):
    name: str | None = None
    number_of_games: int | None = None
    match_type: str | None = None


class GameEvent(_GameSummaryModel):
    league: EventLeague = Field(default_factory=EventLeague)
    series: EventSeries = Field(default_factory=EventSeries)
    tournament: EventTournament = Field(default_factory=EventTournament)
    match: EventMatch = Field(default_factory=EventMatch)
    game_position: int | None = None


class GameSummaryArtifactV5(_GameSummaryModel):
    """Provider-neutral game facts plus already-known esports event context."""

    artifact_type: Literal["game_summary"] = "game_summary"
    schema_version: Literal["5"] = "5"
    event: GameEvent = Field(default_factory=GameEvent)
    game: GameInfo
    teams: Teams
    players: list[PlayerGameSummary] = Field(default_factory=list)
    draft: Draft = Field(default_factory=Draft)


__all__ = [
    "EventLeague",
    "EventMatch",
    "EventSeries",
    "EventTournament",
    "GameEvent",
    "GameSummaryArtifactV5",
]
