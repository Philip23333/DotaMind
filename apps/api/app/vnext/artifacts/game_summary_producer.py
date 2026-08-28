"""Produce and store canonical game-summary artifacts."""

from __future__ import annotations

from typing import Protocol

from app.vnext.domain.construction import GameConstructionContext, GameEventContext
from app.vnext.providers.opendota.adapter import (
    OpenDotaAdapter,
    OpenDotaGameConstructionAdapter,
)

from .models import ArtifactRef, game_summary_artifact_ref
from .protocol import Artifact
from .scope import ArtifactScopeRef, ArtifactScopeStore
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
        scope_store: ArtifactScopeStore | None = None,
    ) -> None:
        self._opendota = opendota
        self._construction_adapter = construction_adapter
        self._builder = builder
        self._store = store
        self._scope_store = scope_store

    async def produce(
        self,
        valve_match_id: int,
        *,
        event_context: GameEventContext | None = None,
        scope_refs: list[ArtifactScopeRef] | None = None,
    ) -> ArtifactRef:
        source = await self._opendota.get_game_construction_match(valve_match_id)
        context = self._construction_adapter.to_construction_context(source.item)
        if event_context is not None:
            context = context.model_copy(update={"event": event_context})
        artifact = self._builder.build(context)
        ref = self._artifact_ref(artifact)
        await self._store.put(ref, artifact)
        if self._scope_store is not None:
            for scope in scope_refs or []:
                await self._scope_store.add(scope, ref)
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
