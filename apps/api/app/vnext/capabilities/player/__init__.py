"""Steam-account-based player capability contracts."""

from .profile import PlayerProfileInput, PlayerProfileResult
from .recent_games import PlayerRecentGame, PlayerRecentGamesInput, PlayerRecentGamesResult

__all__ = [
    "PlayerProfileInput",
    "PlayerProfileResult",
    "PlayerRecentGame",
    "PlayerRecentGamesInput",
    "PlayerRecentGamesResult",
]
