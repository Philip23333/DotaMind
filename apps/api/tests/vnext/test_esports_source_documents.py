from __future__ import annotations

import asyncio
import json

from app.vnext.artifacts import (
    ArtifactGrepper,
    ArtifactReader,
    MemoryArtifactStore,
    SourceDocumentArtifact,
)
from app.vnext.capabilities.esports.pandascore import PandaScoreEsportsSearch
from app.vnext.providers.pandascore.locator import PandaScoreLocatorIndex
from app.vnext.providers.pandascore.models import PandaScoreMatch
from tests.vnext.phase2_support import FakePandaScore


def test_esports_search_externalizes_source_document_and_returns_bounded_observation() -> None:
    panda = FakePandaScore()
    store = MemoryArtifactStore()
    capability = PandaScoreEsportsSearch(panda, PandaScoreLocatorIndex(), store)

    async def exercise():
        result = await capability.search(
            query="Grand Final",
            within=None,
            teams=[],
            time_scope="all",
            limit=10,
        )
        record = next(item for item in result.records if item.kind == "match")
        assert record.artifact_ref is not None
        artifact = await store.get(record.artifact_ref)
        read = await ArtifactReader(store).read(record.artifact_ref, path="facts.results")
        grep = await ArtifactGrepper(store).grep("Grand Final", ["source_document"], 10)
        return record, artifact, read, grep

    record, artifact, read, grep = asyncio.run(exercise())

    assert record.facts["name"].startswith("Grand Final")
    assert record.facts["status"] == "finished"
    assert record.facts["sections"]["opponents"]["count"] == 2
    assert record.facts["sections"]["results"]["count"] == 2
    assert record.facts["sections"]["games"]["count"] == 3
    assert not _contains_provider_identity(record.facts)

    assert isinstance(artifact, SourceDocumentArtifact)
    assert artifact.source == "pandascore"
    assert artifact.kind == "match"
    assert artifact.facts["id"] == 30004
    assert len(artifact.facts["results"]) == 2
    assert len(read.value) == 2
    assert grep.returned >= 1
    assert any(match.ref == record.artifact_ref for match in grep.matches)


def test_pandascore_models_retain_additional_source_fields_for_documents() -> None:
    match = PandaScoreMatch.model_validate(
        {
            "id": 1,
            "name": "Example",
            "status": "finished",
            "future_source_field": {"nested": "kept"},
        }
    )

    dumped = match.model_dump(mode="json", by_alias=True)

    assert dumped["future_source_field"] == {"nested": "kept"}


def _contains_provider_identity(value: object) -> bool:
    if isinstance(value, dict):
        for key, child in value.items():
            if key == "id" or key.endswith("_id") or key.endswith("_ids"):
                return True
            if _contains_provider_identity(child):
                return True
        return False
    if isinstance(value, list):
        return any(_contains_provider_identity(child) for child in value)
    if isinstance(value, str):
        return any(token in value for token in ("30004", "72001", "72002", "72003"))
    return False
