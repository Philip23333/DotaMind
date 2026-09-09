"""Closed semantic esports capability contracts."""

from .dtos import (
    LeagueDTO,
    SeriesDTO,
    TeamRefDTO,
    TournamentDTO,
    TournamentParticipantDTO,
    TournamentRosterPlayerDTO,
)
from .league import LeagueSearchInput, LeagueSearchResult
from .match import (
    CompetitionSummary,
    MatchItem,
    MatchScore,
    MatchSearchInput,
    MatchSearchResult,
    SeriesSummary,
    TeamSummary,
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
from .team import TeamItem, TeamModel, TeamSearchInput, TeamSearchResult
from .tournament import (
    TournamentModel,
    TournamentSearchInput,
    TournamentSearchResult,
)

__all__ = [
    "CompetitionSummary",
    "LeagueDTO",
    "LeagueSearchInput",
    "LeagueSearchResult",
    "MatchItem",
    "MatchScore",
    "MatchSearchInput",
    "MatchSearchResult",
    "PlayerItem",
    "PlayerModel",
    "PlayerSearchInput",
    "PlayerSearchResult",
    "PlayerTeamSummary",
    "SeriesDTO",
    "SeriesModel",
    "SeriesSearchInput",
    "SeriesSearchResult",
    "TeamRefDTO",
    "SeriesTeamsInput",
    "SeriesTeamsResult",
    "SeriesSummary",
    "TeamItem",
    "TeamModel",
    "TeamSearchInput",
    "TeamSearchResult",
    "TeamSummary",
    "TournamentDTO",
    "TournamentModel",
    "TournamentParticipantDTO",
    "TournamentRosterPlayerDTO",
    "TournamentSearchInput",
    "TournamentSearchResult",
]
