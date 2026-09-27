"""STRATZ GraphQL provider implementation for vNext capabilities."""

from .client import (
    StratzGraphQLClient,
    StratzGraphQLError,
    StratzHTTPError,
    StratzResponseError,
    StratzTimeoutError,
    StratzTransportError,
)
from .player_profile import StratzPlayerProfileAdapter
from .player_recent_games import StratzPlayerRecentGamesAdapter

__all__ = [
    "StratzGraphQLError",
    "StratzGraphQLClient",
    "StratzHTTPError",
    "StratzPlayerProfileAdapter",
    "StratzPlayerRecentGamesAdapter",
    "StratzResponseError",
    "StratzTimeoutError",
    "StratzTransportError",
]
