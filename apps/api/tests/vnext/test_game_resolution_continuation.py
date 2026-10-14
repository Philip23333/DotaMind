from __future__ import annotations

import asyncio
from copy import deepcopy
from datetime import UTC, datetime
from typing import Any

import pytest
from pydantic import ValidationError

from app.vnext.artifacts.retrieval import ArtifactPathNotFoundError
from app.vnext.artifacts.store import (
    ArtifactNotFoundError,
    SessionArtifactStore,
)
from app.vnext.capabilities.esports.game_resolution import (
    EsportsGameResolutionResult,
    EsportsGameResolveInput,
)
from app.vnext.capabilities.esports.game_resolution_continuation import (
    GameResolutionContinuation,
)
from app.vnext.tools.errors import StructuredToolError

_MATCH_DOCUMENT = {
    "items": [
        {
            "id": 1743565,
            "name": "LYNX vs Z10",
            "status": "running",
            "draw": False,
            "forfeit": False,
            "rescheduled": False,
        },
        {
            "id": 1743566,
            "name": "Other Match",
            "status": "finished",
            "draw": False,
            "forfeit": False,
            "rescheduled": False,
        },
    ],
    "page": 1,
    "limit": 20,
    "anomalies": [],
}


def _result() -> EsportsGameResolutionResult:
    return EsportsGameResolutionResult(
        status="unresolved",
        game_position=4,
        valve_game_id=None,
        method=None,
        reason="evidence_insufficient",
        providers=["pandascore", "opendota"],
        retrieved_at=datetime(2026, 10, 14, 8, 0, tzinfo=UTC),
        data={"source_fact": "preserved"},
    )


class _FakeService:
    def __init__(self, output: Any | BaseException) -> None:
        self.output = output
        self.calls: list[tuple[int, int, dict[int, int]]] = []

    async def resolve(
        self,
        match_id: int,
        game_position: int,
        *,
        confirmed_mappings: dict[int, int],
    ) -> EsportsGameResolutionResult:
        self.calls.append((match_id, game_position, confirmed_mappings))
        if isinstance(self.output, BaseException):
            raise self.output
        return self.output


def _request(ref: str, path: str = "items.0") -> EsportsGameResolveInput:
    return EsportsGameResolveInput(
        match_artifact_ref=ref,
        match_path=path,
        game_position=4,
    )


def test_continuation_selects_match_and_passes_only_internal_identity() -> None:
    store = SessionArtifactStore()
    original = deepcopy(_MATCH_DOCUMENT)
    ref = asyncio.run(store.put(_MATCH_DOCUMENT, source_tool="esports.match.search"))
    service = _FakeService(_result())
    continuation = GameResolutionContinuation(store, service)  # type: ignore[arg-type]

    result = asyncio.run(continuation.resolve(_request(ref)))

    assert result.reason == "evidence_insufficient"
    assert service.calls == [(1743565, 4, {})]
    assert _MATCH_DOCUMENT == original
    assert asyncio.run(store.get(ref)) == original


@pytest.mark.parametrize("source_tool", [None, "artifact.read", "esports.match.search.other"])
def test_continuation_rejects_missing_or_wrong_artifact_source(source_tool: str | None) -> None:
    store = SessionArtifactStore()
    ref = asyncio.run(store.put(_MATCH_DOCUMENT, source_tool=source_tool))
    service = _FakeService(_result())
    continuation = GameResolutionContinuation(store, service)  # type: ignore[arg-type]

    with pytest.raises(StructuredToolError) as captured:
        asyncio.run(continuation.resolve(_request(ref)))

    assert captured.value.code == "artifact_type_mismatch"
    assert service.calls == []


def test_document_cannot_forge_its_own_source_metadata() -> None:
    document = {**deepcopy(_MATCH_DOCUMENT), "source_tool": "esports.match.search"}
    store = SessionArtifactStore()
    ref = asyncio.run(store.put(document))
    service = _FakeService(_result())
    continuation = GameResolutionContinuation(store, service)  # type: ignore[arg-type]

    with pytest.raises(StructuredToolError) as captured:
        asyncio.run(continuation.resolve(_request(ref)))

    assert captured.value.code == "artifact_type_mismatch"
    assert service.calls == []


@pytest.mark.parametrize(
    "document",
    [
        [],
        {"items": "not a list", "page": 1, "limit": 20, "anomalies": []},
        {"items": [], "page": 1, "limit": 20, "anomalies": [], "extra": True},
    ],
)
def test_continuation_rejects_invalid_match_search_documents(document: Any) -> None:
    store = SessionArtifactStore()
    ref = asyncio.run(store.put(document, source_tool="esports.match.search"))
    service = _FakeService(_result())
    continuation = GameResolutionContinuation(store, service)  # type: ignore[arg-type]

    with pytest.raises(StructuredToolError) as captured:
        asyncio.run(continuation.resolve(_request(ref)))

    assert captured.value.code == "artifact_type_mismatch"
    assert service.calls == []


@pytest.mark.parametrize("bad_id", [True, 0, -1, "1743565", 1743565.0])
def test_continuation_requires_strict_positive_selected_match_id(bad_id: Any) -> None:
    document = deepcopy(_MATCH_DOCUMENT)
    document["items"][0]["id"] = bad_id
    store = SessionArtifactStore()
    ref = asyncio.run(store.put(document, source_tool="esports.match.search"))
    service = _FakeService(_result())
    continuation = GameResolutionContinuation(store, service)  # type: ignore[arg-type]

    with pytest.raises(StructuredToolError) as captured:
        asyncio.run(continuation.resolve(_request(ref)))

    assert captured.value.code == "artifact_type_mismatch"
    assert service.calls == []


def test_continuation_reports_missing_item_path_without_service_call() -> None:
    store = SessionArtifactStore()
    ref = asyncio.run(store.put(_MATCH_DOCUMENT, source_tool="esports.match.search"))
    service = _FakeService(_result())
    continuation = GameResolutionContinuation(store, service)  # type: ignore[arg-type]

    with pytest.raises(ArtifactPathNotFoundError):
        asyncio.run(continuation.resolve(_request(ref, "items.2")))

    assert service.calls == []


@pytest.mark.parametrize(
    "path",
    ["", "items.-1", "items.0.games.0", "items.0.id", "games.0"],
)
def test_public_input_rejects_paths_outside_match_collection(path: str) -> None:
    with pytest.raises(ValidationError):
        EsportsGameResolveInput(
            match_artifact_ref="artifact:tool:" + "a" * 32,
            match_path=path,
            game_position=4,
        )


def test_public_input_accepts_nonnegative_decimal_item_path() -> None:
    request = EsportsGameResolveInput(
        match_artifact_ref="artifact:tool:" + "a" * 32,
        match_path="items.00",
        game_position=1,
    )
    assert request.match_path == "items.00"


@pytest.mark.parametrize("position", [True, 0, -1, 1.0, "4"])
def test_public_input_rejects_non_positive_or_non_integer_game_position(
    position: Any,
) -> None:
    with pytest.raises(ValidationError):
        EsportsGameResolveInput(
            match_artifact_ref="artifact:tool:" + "a" * 32,
            match_path="items.0",
            game_position=position,
        )


def test_public_input_is_closed_and_requires_nonempty_strings() -> None:
    base = {
        "match_artifact_ref": "artifact:tool:" + "a" * 32,
        "match_path": "items.0",
        "game_position": 1,
    }
    with pytest.raises(ValidationError):
        EsportsGameResolveInput.model_validate({**base, "match_id": 1743565})
    with pytest.raises(ValidationError):
        EsportsGameResolveInput.model_validate({**base, "match_artifact_ref": ""})
    with pytest.raises(ValidationError):
        EsportsGameResolveInput.model_validate({**base, "match_artifact_ref": 1})


def test_continuation_preserves_service_errors_and_cancellation() -> None:
    store = SessionArtifactStore()
    ref = asyncio.run(store.put(_MATCH_DOCUMENT, source_tool="esports.match.search"))
    provider_error = StructuredToolError("provider_http_error", "source unavailable")
    failed = GameResolutionContinuation(
        store, _FakeService(provider_error)  # type: ignore[arg-type]
    )
    with pytest.raises(StructuredToolError) as captured:
        asyncio.run(failed.resolve(_request(ref)))
    assert captured.value is provider_error

    cancelled = GameResolutionContinuation(
        store, _FakeService(asyncio.CancelledError())  # type: ignore[arg-type]
    )
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(cancelled.resolve(_request(ref)))


def test_missing_artifact_remains_not_found() -> None:
    store = SessionArtifactStore()
    service = _FakeService(_result())
    continuation = GameResolutionContinuation(store, service)  # type: ignore[arg-type]
    ref = "artifact:tool:" + "0" * 32

    with pytest.raises(ArtifactNotFoundError):
        asyncio.run(continuation.resolve(_request(ref)))

    assert service.calls == []


def test_artifact_reference_cannot_cross_session_stores() -> None:
    source_store = SessionArtifactStore()
    ref = asyncio.run(
        source_store.put(_MATCH_DOCUMENT, source_tool="esports.match.search")
    )
    other_store = SessionArtifactStore()
    service = _FakeService(_result())
    continuation = GameResolutionContinuation(other_store, service)  # type: ignore[arg-type]

    with pytest.raises(ArtifactNotFoundError):
        asyncio.run(continuation.resolve(_request(ref)))

    assert service.calls == []
