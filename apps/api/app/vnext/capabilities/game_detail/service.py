"""Source-backed detailed recorded-game capability service."""

from __future__ import annotations

from app.vnext.providers.opendota.adapter import OpenDotaAdapter, OpenDotaProviderError

from .errors import GameDetailProviderError
from .models import GameDetailPayload, GameDetailRequest

_SOURCE = "opendota"


class GameDetailService:
    """Fetch one complete OpenDota game document."""

    def __init__(self, opendota: OpenDotaAdapter) -> None:
        self._opendota = opendota

    async def detail(self, request: GameDetailRequest) -> GameDetailPayload:
        try:
            provider_object = await self._opendota.get_game_detail(request.valve_game_id)
        except OpenDotaProviderError as exc:
            raise GameDetailProviderError(
                source=_SOURCE,
                valve_game_id=request.valve_game_id,
            ) from exc

        document = provider_object.item.model_dump(mode="json", by_alias=True)
        return GameDetailPayload(
            source=_SOURCE,
            valve_game_id=request.valve_game_id,
            facts=document,
        )


__all__ = ["GameDetailService"]
