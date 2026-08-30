"""Capability boundary for source-backed esports search."""

from __future__ import annotations

from app.vnext.artifacts import (
    ArtifactStore,
    SourceDocumentArtifact,
    bounded_source_observation,
    source_document_artifact_ref,
)

from .errors import ArtifactExternalizationError, EsportsInvalidArgumentsError
from .models import (
    EsportsSearchProvider,
    EsportsSearchRequest,
    EsportsSearchResult,
    EsportsSearchWarning,
    ProviderEntity,
    SourceRecord,
)


class EsportsSearchService:
    """Validate requests and externalize final provider entities as Artifacts."""

    def __init__(self, provider: EsportsSearchProvider, artifact_store: ArtifactStore) -> None:
        self._provider = provider
        self._artifact_store = artifact_store

    async def search(self, request: EsportsSearchRequest) -> EsportsSearchResult:
        self._validate(request)
        batch = await self._provider.search(request)
        entities = self._deduplicate(batch.entities)
        final_entities = entities[: request.limit]
        truncated = batch.truncated or len(entities) > request.limit
        records: list[SourceRecord] = []
        warnings: list[EsportsSearchWarning] = []
        for entity in final_entities:
            try:
                records.append(await self._externalize(entity))
            except ArtifactExternalizationError:
                warnings.append(
                    EsportsSearchWarning(
                        code="artifact_externalization_failed",
                        source=entity.source,
                        kind=entity.kind,
                    )
                )
        if final_entities and not records:
            first = final_entities[0]
            raise ArtifactExternalizationError(source=first.source, kind=first.kind)
        return EsportsSearchResult(
            records=records,
            truncated=truncated,
            partial=bool(warnings),
            warnings=warnings,
        )

    @staticmethod
    def _validate(request: EsportsSearchRequest) -> None:
        if request.teams and request.kind != "match":
            raise EsportsInvalidArgumentsError(
                "teams is supported only when kind is match",
                details={"argument": "teams", "capability": "match"},
            )
        if request.time_scope is not None and request.kind not in {
            "series",
            "tournament",
            "match",
        }:
            raise EsportsInvalidArgumentsError(
                "time_scope is supported only for series, tournament, or match",
                details={"argument": "time_scope", "kind": request.kind},
            )
        if any(not team.strip() for team in request.teams):
            raise EsportsInvalidArgumentsError(
                "teams must not contain blank names",
                details={"argument": "teams"},
            )

    @staticmethod
    def _deduplicate(entities: list[ProviderEntity]) -> list[ProviderEntity]:
        unique: list[ProviderEntity] = []
        seen: set[tuple[str, str, int | str]] = set()
        for entity in entities:
            identity = (entity.source, entity.kind, entity.source_identity)
            if identity in seen:
                continue
            seen.add(identity)
            unique.append(entity)
        return unique

    async def _externalize(self, entity: ProviderEntity) -> SourceRecord:
        ref = source_document_artifact_ref(
            entity.source,
            entity.kind,
            entity.source_identity,
        )
        try:
            await self._artifact_store.put(
                ref,
                SourceDocumentArtifact(
                    source=entity.source,
                    kind=entity.kind,
                    fetched_at=entity.fetched_at,
                    facts=entity.document,
                ),
            )
        except Exception as exc:
            raise ArtifactExternalizationError(
                source=entity.source,
                kind=entity.kind,
            ) from exc
        return SourceRecord(
            source=entity.source,
            kind=entity.kind,
            artifact_ref=ref,
            facts=bounded_source_observation(entity.document),
        )


__all__ = ["EsportsSearchService"]
