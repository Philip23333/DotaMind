"""Produce and store canonical game-summary artifacts."""

from __future__ import annotations

from app.vnext.providers.opendota.adapter import (
    OpenDotaAdapter,
    OpenDotaGameConstructionAdapter,
)

from .game_summary import GameSummaryArtifact
from .game_summary_builder import GameSummaryBuilder
from .models import ArtifactRef
from .store import ArtifactStore


class GameSummaryArtifactProducer:
    """Coordinate OpenDota fetch, construction, building, and storage."""

    def __init__(
        self,
        opendota: OpenDotaAdapter,
        construction_adapter: OpenDotaGameConstructionAdapter,
        builder: GameSummaryBuilder,
        store: ArtifactStore,
    ) -> None:
        self._opendota = opendota
        self._construction_adapter = construction_adapter
        self._builder = builder
        self._store = store

    async def produce(self, valve_match_id: int) -> ArtifactRef:
        source = await self._opendota.get_game_construction_match(valve_match_id)
        context = self._construction_adapter.to_construction_context(source.item)
        artifact = self._builder.build(context)
        ref = self._artifact_ref(artifact)
        self._store.put(ref, artifact)
        return ref

    @staticmethod
    def _artifact_ref(artifact: GameSummaryArtifact) -> ArtifactRef:
        return ArtifactRef(
            id=(
                f"{artifact.artifact_type}:"
                f"{artifact.schema_version}:"
                f"{artifact.game.valve_match_id}"
            ),
            artifact_type=artifact.artifact_type,
            schema_version=artifact.schema_version,
        )


__all__ = ["GameSummaryArtifactProducer"]
