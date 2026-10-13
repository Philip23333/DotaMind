"""OpenDota provider implementations for game detail and League discovery."""

from .client import (
    OpenDotaClient,
    OpenDotaHTTPError,
    OpenDotaResponseError,
    OpenDotaTimeoutError,
    OpenDotaTransportError,
)
from .discovery import OpenDotaDiscoveryAdapter
from .game_detail import OpenDotaGameDetailAdapter

__all__ = [
    "OpenDotaClient",
    "OpenDotaDiscoveryAdapter",
    "OpenDotaGameDetailAdapter",
    "OpenDotaHTTPError",
    "OpenDotaResponseError",
    "OpenDotaTimeoutError",
    "OpenDotaTransportError",
]
