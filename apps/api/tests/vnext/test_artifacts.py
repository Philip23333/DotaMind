"""Tests for the generic vNext artifact store foundation."""

import asyncio
from dataclasses import dataclass

import pytest
from pydantic import ValidationError

from app.vnext.artifacts import (
    ArtifactNotFoundError,
    ArtifactRef,
    ArtifactTypeMismatchError,
    MemoryArtifactStore,
)


@dataclass(frozen=True)
class TestArtifact:
    __test__ = False

    artifact_type: str = "test"
    schema_version: str = "1"
    value: str = "payload"


def test_artifact_ref_is_frozen_and_contains_only_identity_fields() -> None:
    ref = ArtifactRef(id="artifact:test:1", artifact_type="test", schema_version="1")

    assert set(ArtifactRef.model_fields) == {"id", "artifact_type", "schema_version"}
    with pytest.raises(ValidationError):
        ref.id = "artifact:test:2"


def test_put_get_preserves_artifact_identity() -> None:
    store = MemoryArtifactStore()
    ref = ArtifactRef(id="artifact:test:1", artifact_type="test", schema_version="1")
    artifact = TestArtifact()

    asyncio.run(store.put(ref, artifact))

    assert asyncio.run(store.get(ref)) is artifact


def test_exists_changes_after_put() -> None:
    store = MemoryArtifactStore()
    ref = ArtifactRef(id="artifact:test:1", artifact_type="test", schema_version="1")

    assert asyncio.run(store.exists(ref)) is False

    asyncio.run(store.put(ref, TestArtifact()))

    assert asyncio.run(store.exists(ref)) is True


def test_get_missing_artifact_raises_not_found_error() -> None:
    store = MemoryArtifactStore()
    ref = ArtifactRef(id="artifact:test:missing", artifact_type="test", schema_version="1")

    with pytest.raises(ArtifactNotFoundError, match="artifact:test:missing"):
        asyncio.run(store.get(ref))


@pytest.mark.parametrize(
    ("ref_type", "ref_version", "artifact_type", "artifact_version"),
    [
        ("expected", "1", "actual", "1"),
        ("test", "2", "test", "1"),
    ],
)
def test_put_rejects_type_or_schema_mismatch(
    ref_type: str,
    ref_version: str,
    artifact_type: str,
    artifact_version: str,
) -> None:
    store = MemoryArtifactStore()
    ref = ArtifactRef(
        id="artifact:test:mismatch",
        artifact_type=ref_type,
        schema_version=ref_version,
    )
    artifact = TestArtifact(artifact_type=artifact_type, schema_version=artifact_version)

    with pytest.raises(ArtifactTypeMismatchError):
        asyncio.run(store.put(ref, artifact))


def test_put_replaces_existing_value_when_reference_is_compatible() -> None:
    store = MemoryArtifactStore()
    ref = ArtifactRef(id="artifact:test:replace", artifact_type="test", schema_version="1")
    first = TestArtifact(value="first")
    second = TestArtifact(value="second")

    asyncio.run(store.put(ref, first))
    asyncio.run(store.put(ref, second))

    assert asyncio.run(store.get(ref)) is second


@pytest.mark.parametrize(
    ("ref_type", "ref_version"),
    [("actual", "1"), ("test", "2")],
)
def test_get_rejects_reference_metadata_mismatch(ref_type: str, ref_version: str) -> None:
    store = MemoryArtifactStore()
    stored_ref = ArtifactRef(
        id="artifact:test:stored-mismatch",
        artifact_type="test",
        schema_version="1",
    )
    requested_ref = ArtifactRef(
        id=stored_ref.id,
        artifact_type=ref_type,
        schema_version=ref_version,
    )
    asyncio.run(store.put(stored_ref, TestArtifact()))

    with pytest.raises(ArtifactTypeMismatchError):
        asyncio.run(store.get(requested_ref))
