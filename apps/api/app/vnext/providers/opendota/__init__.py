"""OpenDota provider implementation for existing single-game records."""

from .client import (
    OpenDotaClient,
    OpenDotaHTTPError,
    OpenDotaResponseError,
    OpenDotaTimeoutError,
    OpenDotaTransportError,
)
from .game_detail import OpenDotaGameDetailAdapter

__all__ = [
    "OpenDotaClient",
    "OpenDotaGameDetailAdapter",
    "OpenDotaHTTPError",
    "OpenDotaResponseError",
    "OpenDotaTimeoutError",
    "OpenDotaTransportError",
]
