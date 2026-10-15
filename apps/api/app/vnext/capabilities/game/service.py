"""Build the public game-detail result from an internal OpenDota record."""

from __future__ import annotations

from app.vnext.providers.opendota.game_detail import OpenDotaGameDetailAdapter

from .detail import GameDetailInput, GameDetailResult


class GameDetailService:
    """Own public detail conversion without changing the resolver's source record."""

    def __init__(self, provider: OpenDotaGameDetailAdapter) -> None:
        self._provider = provider

    async def get_game_detail(self, query: GameDetailInput) -> GameDetailResult:
        record = await self._provider.get_game_record(query.valve_game_id)
        return GameDetailResult(
            valve_game_id=record.match_id,
            provider=record.provider,
            retrieved_at=record.retrieved_at,
            data=record.data,
        )
