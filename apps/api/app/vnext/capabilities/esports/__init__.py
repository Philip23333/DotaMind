"""Closed semantic esports capability contracts."""

from .dtos import (
    CurrentRosterPlayerDTO,
    LeagueDTO,
    MatchDTO,
    MatchGameDTO,
    MatchParticipantDTO,
    PlayerRole,
    SeriesDTO,
    TeamDTO,
    TeamRefDTO,
    TournamentDTO,
    TournamentParticipantDTO,
    TournamentRosterPlayerDTO,
)
from .league import LeagueSearchInput, LeagueSearchResult
from .match import (
    MatchModel,
    MatchSearchInput,
    MatchSearchResult,
)
from .player import (
    PlayerItem,
    PlayerModel,
    PlayerSearchInput,
    PlayerSearchResult,
    PlayerTeamSummary,
)
from .series import (
    SeriesModel,
    SeriesSearchInput,
    SeriesSearchResult,
    SeriesTeamsInput,
    SeriesTeamsResult,
)
from .team import TeamModel, TeamSearchInput, TeamSearchResult
from .tournament import (
    TournamentModel,
    TournamentSearchInput,
    TournamentSearchResult,
)

__all__ = [
    "LeagueDTO",
    "LeagueSearchInput",
    "LeagueSearchResult",
    "MatchDTO",
    "MatchGameDTO",
    "MatchModel",
    "MatchParticipantDTO",
    "MatchSearchInput",
    "MatchSearchResult",
    "CurrentRosterPlayerDTO",
    "PlayerItem",
    "PlayerModel",
    "PlayerSearchInput",
    "PlayerSearchResult",
    "PlayerTeamSummary",
    "PlayerRole",
    "SeriesDTO",
    "SeriesModel",
    "SeriesSearchInput",
    "SeriesSearchResult",
    "TeamRefDTO",
    "TeamDTO",
    "SeriesTeamsInput",
    "SeriesTeamsResult",
    "TeamModel",
    "TeamSearchInput",
    "TeamSearchResult",
    "TournamentDTO",
    "TournamentModel",
    "TournamentParticipantDTO",
    "TournamentRosterPlayerDTO",
    "TournamentSearchInput",
    "TournamentSearchResult",
]
