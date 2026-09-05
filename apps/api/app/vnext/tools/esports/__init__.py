"""Model-facing esports tools."""

from .league import LEAGUE_SEARCH_DESCRIPTION, register_league_tool
from .match import MATCH_SEARCH_DESCRIPTION, register_match_tool
from .player import PLAYER_SEARCH_DESCRIPTION, register_player_tool
from .series import SERIES_SEARCH_DESCRIPTION, register_series_tool
from .team import TEAM_SEARCH_DESCRIPTION, register_team_tool
from .tournament import (
    TOURNAMENT_ROSTERS_DESCRIPTION,
    TOURNAMENT_SEARCH_DESCRIPTION,
    register_tournament_rosters_tool,
    register_tournament_tool,
)

__all__ = [
    "LEAGUE_SEARCH_DESCRIPTION",
    "MATCH_SEARCH_DESCRIPTION",
    "PLAYER_SEARCH_DESCRIPTION",
    "SERIES_SEARCH_DESCRIPTION",
    "TEAM_SEARCH_DESCRIPTION",
    "TOURNAMENT_ROSTERS_DESCRIPTION",
    "TOURNAMENT_SEARCH_DESCRIPTION",
    "register_league_tool",
    "register_match_tool",
    "register_player_tool",
    "register_series_tool",
    "register_team_tool",
    "register_tournament_rosters_tool",
    "register_tournament_tool",
]
