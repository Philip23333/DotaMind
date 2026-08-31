"""Source-backed detailed recorded-game capability service."""

from __future__ import annotations

from app.vnext.artifacts import (
    ArtifactStore,
    GameDetailArtifact,
    bounded_source_observation,
    game_detail_artifact_ref,
)
from app.vnext.providers.opendota.adapter import OpenDotaAdapter, OpenDotaProviderError

from .errors import GameDetailArtifactError, GameDetailProviderError
from .models import GameDetailRequest, GameDetailResult

_SOURCE = "opendota"


class GameDetailService:
    """Fetch one complete OpenDota game document and externalize it atomically."""

    def __init__(self, opendota: OpenDotaAdapter, artifact_store: ArtifactStore) -> None:
        self._opendota = opendota
        self._artifact_store = artifact_store

    async def detail(self, request: GameDetailRequest) -> GameDetailResult:
        try:
            provider_object = await self._opendota.get_game_detail(request.valve_game_id)
        except OpenDotaProviderError as exc:
            raise GameDetailProviderError(
                source=_SOURCE,
                valve_game_id=request.valve_game_id,
            ) from exc

        document = provider_object.item.model_dump(mode="json", by_alias=True)
        ref = game_detail_artifact_ref(request.valve_game_id)
        try:
            await self._artifact_store.put(
                ref,
                GameDetailArtifact(
                    source=_SOURCE,
                    valve_game_id=request.valve_game_id,
                    fetched_at=provider_object.fetched_at,
                    facts=document,
                ),
            )
        except Exception as exc:
            raise GameDetailArtifactError(
                source=_SOURCE,
                valve_game_id=request.valve_game_id,
            ) from exc
        return GameDetailResult(
            source=_SOURCE,
            valve_game_id=request.valve_game_id,
            artifact_ref=ref,
            facts=bounded_source_observation(document),
        )


__all__ = ["GameDetailService"]
