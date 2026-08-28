"""Deterministic tests for generic canonical artifact corpus grep."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from pydantic import BaseModel, ValidationError

from app.vnext.artifacts import ArtifactGrepper, ArtifactRef, MemoryArtifactStore
from app.vnext.composition import build_vnext_registry
from app.vnext.llm.protocol import ToolCall
from app.vnext.tools.artifacts.retrieval import ArtifactGrepInput
from tests.vnext.phase2_support import fixture_services, fixture_vnext_services


class SearchArtifact(BaseModel):
    artifact_type: str
    schema_version: str
    title: str
    payload: dict[str, Any]


def _grep(
    store: MemoryArtifactStore,
    pattern: str,
    artifact_types: list[str] | None = None,
    limit: int = ArtifactGrepper.DEFAULT_LIMIT,
):
    return asyncio.run(ArtifactGrepper(store).grep(pattern, artifact_types, limit))


def _put(
    store: MemoryArtifactStore,
    ref: ArtifactRef,
    *,
    title: str,
    payload: dict[str, Any],
) -> None:
    asyncio.run(
        store.put(
            ref,
            SearchArtifact(
                artifact_type=ref.artifact_type,
                schema_version=ref.schema_version,
                title=title,
                payload=payload,
            ),
        )
    )


def test_grep_recursively_returns_case_insensitive_scalar_matches_and_paths() -> None:
    store = MemoryArtifactStore()
    ref = ArtifactRef(id="game_summary:4:1", artifact_type="game_summary", schema_version="4")
    _put(
        store,
        ref,
        title="Game summary",
        payload={
            "players": [{"identity": {"registered_name": "Malr1ne"}}],
            "featured": True,
            "net_worth": 18500,
            "ratio": 18.5,
        },
    )

    player = _grep(store, "malr1ne")
    truthy = _grep(store, "TRUE")
    number = _grep(store, "18500")
    decimal = _grep(store, "18.5")

    assert [(match.ref, match.path, match.preview) for match in player.matches] == [
        (ref, "payload.players.0.identity.registered_name", "Malr1ne")
    ]
    assert [(match.path, match.preview) for match in truthy.matches] == [
        ("payload.featured", "true")
    ]
    assert [(match.path, match.preview) for match in number.matches] == [
        ("payload.net_worth", "18500")
    ]
    assert [(match.path, match.preview) for match in decimal.matches] == [
        ("payload.ratio", "18.5")
    ]


def test_grep_uses_the_same_engine_for_multiple_artifact_types_and_type_filtering() -> None:
    store = MemoryArtifactStore()
    game_ref = ArtifactRef(
        id="game_summary:4:1", artifact_type="game_summary", schema_version="4"
    )
    other_ref = ArtifactRef(id="other:1:2", artifact_type="other", schema_version="1")
    _put(store, game_ref, title="Team Falcons game", payload={})
    _put(store, other_ref, title="TI 2026", payload={"participants": [{"name": "Team Falcons"}]})

    all_types = _grep(store, "FALCONS")
    only_other = _grep(store, "falcons", ["other"])

    assert [(match.ref, match.path) for match in all_types.matches] == [
        (game_ref, "title"),
        (other_ref, "payload.participants.0.name"),
    ]
    assert [(match.ref, match.path) for match in only_other.matches] == [
        (other_ref, "payload.participants.0.name")
    ]


def test_grep_bounds_results_and_keeps_the_matching_text_in_a_bounded_preview() -> None:
    store = MemoryArtifactStore()
    ref = ArtifactRef(id="test:1:1", artifact_type="test", schema_version="1")
    _put(
        store,
        ref,
        title="needle one",
        payload={
            "second": "needle two",
            "third": "needle three",
            "long": f"{'x' * 300}needle{'y' * 300}",
        },
    )

    bounded = _grep(store, "needle", limit=2)
    long_preview = _grep(store, "needle", limit=10).matches[-1].preview

    assert [match.path for match in bounded.matches] == ["title", "payload.second"]
    assert bounded.returned == 2
    assert bounded.truncated is True
    assert "needle" in long_preview
    assert len(long_preview) <= ArtifactGrepper.MAX_PREVIEW_LENGTH


def test_grep_input_and_direct_boundary_reject_invalid_bounds() -> None:
    with pytest.raises(ValidationError):
        ArtifactGrepInput.model_validate({"pattern": " "})
    with pytest.raises(ValidationError):
        ArtifactGrepInput.model_validate({"pattern": "x" * 257})
    with pytest.raises(ValidationError):
        ArtifactGrepInput.model_validate({"pattern": "x", "limit": 101})

    store = MemoryArtifactStore()
    with pytest.raises(ValueError, match="must not be empty"):
        _grep(store, "")
    with pytest.raises(ValueError, match="between 1 and 100"):
        _grep(store, "x", limit=101)


def test_artifact_grep_tool_searches_stored_content_without_provider_production() -> None:
    series_service, match_service, panda, opendota = fixture_services()
    services = fixture_vnext_services(series_service, match_service, panda, opendota)
    ref = ArtifactRef(id="game_summary:4:88", artifact_type="game_summary", schema_version="4")
    _put(
        services.artifact_store,
        ref,
        title="Stored result",
        payload={"players": [{"name": "Malr1ne"}]},
    )

    result = asyncio.run(
        build_vnext_registry(services).execute(
            ToolCall(
                id="artifact-grep",
                name="artifact.grep",
                arguments={"pattern": "malr1ne", "artifact_types": ["game_summary"]},
            )
        )
    )

    assert result.status == "ok"
    assert result.content == {
        "matches": [
            {
                "ref": ref.model_dump(),
                "path": "payload.players.0.name",
                "preview": "Malr1ne",
            }
        ],
            "returned": 1,
            "truncated": False,
            "coverage": "materialized_only",
        }
    assert opendota.construction_calls == []
