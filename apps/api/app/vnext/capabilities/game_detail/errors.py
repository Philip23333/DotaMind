"""Sanitized game.detail capability failures."""

from __future__ import annotations

from typing import Any


class GameDetailError(RuntimeError):
    """Base class for expected game.detail errors safe for tool mapping."""

    def __init__(self, message: str, *, details: dict[str, Any]) -> None:
        super().__init__(message)
        self.details = details


class GameDetailProviderError(GameDetailError):
    """OpenDota could not provide one requested game detail document."""

    def __init__(self, *, source: str, valve_game_id: int) -> None:
        super().__init__(
            "game detail provider failed",
            details={"source": source, "valve_game_id": valve_game_id},
        )


class GameDetailArtifactError(GameDetailError):
    """The complete detailed-game document could not be externalized."""

    def __init__(self, *, source: str, valve_game_id: int) -> None:
        super().__init__(
            "game detail artifact could not be stored",
            details={"source": source, "valve_game_id": valve_game_id},
        )


__all__ = ["GameDetailArtifactError", "GameDetailError", "GameDetailProviderError"]
