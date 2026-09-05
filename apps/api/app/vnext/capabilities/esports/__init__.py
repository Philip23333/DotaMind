"""Closed semantic esports capability contracts."""

from .league import LeagueItem, LeagueSearchInput, LeagueSearchResult
from .match import (
    CompetitionSummary,
    MatchItem,
    MatchScore,
    MatchSearchInput,
    MatchSearchResult,
    SeriesSummary,
    TeamSummary,
)
from .series import (
    LeagueSummary,
    SeriesItem,
    SeriesModel,
    SeriesSearchInput,
    SeriesSearchResult,
)
from .tournament import (
    TournamentItem,
    TournamentModel,
    TournamentSearchInput,
    TournamentSearchResult,
)

__all__ = [
    "CompetitionSummary",
    "LeagueItem",
    "LeagueSearchInput",
    "LeagueSearchResult",
    "LeagueSummary",
    "MatchItem",
    "MatchScore",
    "MatchSearchInput",
    "MatchSearchResult",
    "SeriesItem",
    "SeriesModel",
    "SeriesSearchInput",
    "SeriesSearchResult",
    "SeriesSummary",
    "TeamSummary",
    "TournamentItem",
    "TournamentModel",
    "TournamentSearchInput",
    "TournamentSearchResult",
]
