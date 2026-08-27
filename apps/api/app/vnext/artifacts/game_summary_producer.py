"""Produce and store canonical game-summary artifacts."""

from __future__ import annotations

from typing import Protocol

from app.vnext.domain.construction import GameConstructionContext
from app.vnext.providers.opendota.adapter import (
    OpenDotaAdapter,
    OpenDotaGameConstructionAdapter,
)

from .models import ArtifactRef, game_summary_artifact_ref
from .protocol import Artifact
from .store import ArtifactStore


class _GameSummaryArtifact(Artifact, Protocol):
    game: object


class _GameSummaryBuilder(Protocol):
    def build(self, context: GameConstructionContext) -> _GameSummaryArtifact:
        """Build one versioned game-summary artifact."""


class GameSummaryArtifactProducer:
    """Coordinate OpenDota fetch, construction, building, and storage."""

    def __init__(
        self,
        opendota: OpenDotaAdapter,
        construction_adapter: OpenDotaGameConstructionAdapter,
        builder: _GameSummaryBuilder,
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
    def _artifact_ref(artifact: _GameSummaryArtifact) -> ArtifactRef:
        game = getattr(artifact, "game", None)
        valve_match_id = getattr(game, "valve_match_id", None)
        if not isinstance(valve_match_id, int):
            raise TypeError("game summary artifact must provide an integer valve_match_id")
        return game_summary_artifact_ref(
            valve_match_id,
            schema_version=artifact.schema_version,
        )


__all__ = ["GameSummaryArtifactProducer"]
