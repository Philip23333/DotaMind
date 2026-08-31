"""Detailed recorded-game capability."""

from .errors import GameDetailArtifactError, GameDetailError, GameDetailProviderError
from .models import GameDetailRequest, GameDetailResult
from .service import GameDetailService

__all__ = [
    "GameDetailArtifactError",
    "GameDetailError",
    "GameDetailProviderError",
    "GameDetailRequest",
    "GameDetailResult",
    "GameDetailService",
]
