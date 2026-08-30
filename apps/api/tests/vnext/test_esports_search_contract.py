"""Contract tests for the source-backed esports-search capability boundary."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone

from app.vnext.artifacts import MemoryArtifactStore
from app.vnext.capabilities.esports.errors import EsportsProviderError
from app.vnext.capabilities.esports.models import (
    EsportsSearchRequest,
    ProviderEntity,
    ProviderSearchBatch,
)
from app.vnext.capabilities.esports.service import EsportsSearchService
from app.vnext.llm.protocol import ToolCall
from app.vnext.tools.domain.esports import register_esports_tools
from app.vnext.tools.registry import ToolRegistry

FETCHED_AT = datetime(2026, 8, 30, tzinfo=timezone.utc)


@dataclass
class StubProvider:
    batch: ProviderSearchBatch
    failure: Exception | None = None

    async def search(self, request: EsportsSearchRequest) -> ProviderSearchBatch:
        if self.failure is not None:
            raise self.failure
        return self.batch


class FailingStore(MemoryArtifactStore):
    async def put(self, ref, artifact) -> None:  # type: ignore[no-untyped-def]
        raise RuntimeError("store unavailable")


class OneFailureStore(MemoryArtifactStore):
    async def put(self, ref, artifact) -> None:  # type: ignore[no-untyped-def]
        if artifact.facts.get("id") == 2:
            raise RuntimeError("store unavailable")
        await super().put(ref, artifact)


def _entity(identity: int | str, name: str, *, source: str = "pandascore") -> ProviderEntity:
    return ProviderEntity(
        source=source,
        kind="team",
        source_identity=identity,
        fetched_at=FETCHED_AT,
        document={"id": identity, "name": name, "players": [{"name": "Player"}]},
    )


def _registry(provider: StubProvider, store: MemoryArtifactStore | None = None) -> ToolRegistry:
    registry = ToolRegistry()
    register_esports_tools(registry, EsportsSearchService(provider, store or MemoryArtifactStore()))
    return registry


def test_model_schema_exposes_only_the_frozen_esports_search_arguments() -> None:
    registry = _registry(StubProvider(ProviderSearchBatch([])))
    schema = next(tool.input_schema for tool in registry.schemas() if tool.name == "esports.search")

    assert set(schema["properties"]) == {"kind", "query", "teams", "time_scope", "limit"}
    assert schema["required"] == ["kind"]
    assert schema["properties"]["limit"]["minimum"] == 1
    assert schema["properties"]["limit"]["maximum"] == 50
    assert schema["properties"]["time_scope"]["anyOf"][1]["type"] == "null"
    assert "game" not in schema["properties"]["kind"]["enum"]
    assert {"within", "locator"}.isdisjoint(schema["properties"])


def test_tool_maps_cross_field_validation_to_invalid_arguments() -> None:
    registry = _registry(StubProvider(ProviderSearchBatch([])))

    result = asyncio.run(
        registry.execute(
            ToolCall(
                id="invalid-teams",
                name="esports.search",
                arguments={"kind": "team", "teams": ["Team Spirit"]},
            )
        )
    )

    assert result.status == "error"
    assert result.error is not None
    assert result.error.code == "invalid_arguments"
    assert result.error.details == {"argument": "teams", "capability": "match"}


def test_tool_maps_provider_and_artifact_failures_to_explicit_errors() -> None:
    provider_registry = _registry(
        StubProvider(
            ProviderSearchBatch([]),
            failure=EsportsProviderError(source="pandascore", kind="match"),
        )
    )
    artifact_registry = _registry(
        StubProvider(
            ProviderSearchBatch(
                [_entity(1, "Team Spirit"), _entity(2, "Team Liquid"), _entity(3, "Team Falcons")]
            )
        ),
        FailingStore(),
    )

    provider_result = asyncio.run(
        provider_registry.execute(
            ToolCall(id="provider", name="esports.search", arguments={"kind": "match"})
        )
    )
    artifact_result = asyncio.run(
        artifact_registry.execute(
            ToolCall(id="artifact", name="esports.search", arguments={"kind": "team"})
        )
    )

    assert provider_result.error is not None
    assert provider_result.error.code == "provider_error"
    assert provider_result.error.details == {"source": "pandascore", "kind": "match"}
    assert artifact_result.error is not None
    assert artifact_result.error.code == "artifact_error"
    assert artifact_result.error.details == {"source": "pandascore", "kind": "team"}


def test_service_deduplicates_exact_identity_and_externalizes_only_final_records() -> None:
    store = MemoryArtifactStore()
    provider = StubProvider(
        ProviderSearchBatch(
            [
                _entity(1, "Team Spirit"),
                _entity(1, "Team Spirit duplicate"),
                _entity(2, "Team Liquid"),
                _entity(3, "Team Falcons"),
            ]
        )
    )
    service = EsportsSearchService(provider, store)

    result = asyncio.run(service.search(EsportsSearchRequest(kind="team", limit=2)))

    assert [record.facts["name"] for record in result.records] == ["Team Spirit", "Team Liquid"]
    assert result.truncated is True
    assert result.partial is False
    assert result.warnings == []
    assert all(record.artifact_ref is not None for record in result.records)

    async def source_document_count() -> int:
        return len([ref async for ref in store.iter_refs(["source_document"])])

    assert asyncio.run(source_document_count()) == 2


def test_service_reports_non_partial_when_all_final_artifacts_are_written() -> None:
    service = EsportsSearchService(
        StubProvider(
            ProviderSearchBatch(
                [_entity(1, "Team Spirit"), _entity(2, "Team Liquid"), _entity(3, "Team Falcons")]
            )
        ),
        MemoryArtifactStore(),
    )

    result = asyncio.run(service.search(EsportsSearchRequest(kind="team", limit=3)))

    assert len(result.records) == 3
    assert result.partial is False
    assert result.warnings == []


def test_tool_returns_partial_success_when_one_final_artifact_write_fails() -> None:
    registry = _registry(
        StubProvider(
            ProviderSearchBatch(
                [_entity(1, "Team Spirit"), _entity(2, "Team Liquid"), _entity(3, "Team Falcons")]
            )
        ),
        OneFailureStore(),
    )

    result = asyncio.run(
        registry.execute(ToolCall(id="partial", name="esports.search", arguments={"kind": "team"}))
    )

    assert result.status == "ok"
    assert result.content["partial"] is True
    assert result.content["warnings"] == [
        {
            "code": "artifact_externalization_failed",
            "source": "pandascore",
            "kind": "team",
        }
    ]
    records = result.content["records"]
    assert [record["facts"]["name"] for record in records] == ["Team Spirit", "Team Falcons"]
    assert all(record["artifact_ref"] for record in records)


def test_same_source_identity_reuses_its_artifact_reference_and_overwrites_document() -> None:
    store = MemoryArtifactStore()
    provider = StubProvider(ProviderSearchBatch([_entity(1, "First name")]))
    service = EsportsSearchService(provider, store)

    first = asyncio.run(service.search(EsportsSearchRequest(kind="team")))
    provider.batch = ProviderSearchBatch([_entity(1, "Second name")])
    second = asyncio.run(service.search(EsportsSearchRequest(kind="team")))

    assert first.records[0].artifact_ref == second.records[0].artifact_ref
    stored = asyncio.run(store.get(second.records[0].artifact_ref))
    assert stored.facts["name"] == "Second name"
    assert second.records[0].facts["sections"]["players"] == {
        "kind": "collection",
        "count": 1,
    }
