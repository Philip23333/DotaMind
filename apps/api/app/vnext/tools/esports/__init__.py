"""Model-facing esports tools."""

from .league import LEAGUE_SEARCH_DESCRIPTION, register_league_tool
from .match import MATCH_SEARCH_DESCRIPTION, register_match_tool

__all__ = [
    "LEAGUE_SEARCH_DESCRIPTION",
    "MATCH_SEARCH_DESCRIPTION",
    "register_league_tool",
    "register_match_tool",
]
