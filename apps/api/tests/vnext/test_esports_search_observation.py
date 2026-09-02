"""Focused contracts for session-local bounded esports.search observations."""

from __future__ import annotations

import asyncio
from typing import Any

import httpx

from app.vnext.artifacts import (
    ArtifactGrepper,
    ArtifactReader,
    SessionArtifactStore,
    ToolResponseExternalizer,
)
from app.vnext.llm.protocol import ToolCall
from app.vnext.providers.pandascore.adapter import PandaScoreAdapter
from app.vnext.providers.pandascore.capabilities import PandaScoreCapabilities
from app.vnext.providers.pandascore.query import PandaScoreNativeQueryExecutor
from app.vnext.tools.artifacts import register_artifact_tools
from app.vnext.tools.domain.esports import register_esports_tools
from app.vnext.tools.domain.esports_observation import EsportsSearchObservationBuilder
from app.vnext.tools.registry import ToolRegistry


def _large_rows() -> list[dict[str, Any]]:
    return [
        {
            "id": 21545,
            "name": "Group Stage",
            "matches": [{"name": "Grand final", "detail": "x" * 1000} for _ in range(20)],
            "unknown_future_field": {"deep": [1, 2, 3]},
        }
        for _ in range(3)
    ]


def _registry(handler: Any) -> tuple[ToolRegistry, PandaScoreAdapter, SessionArtifactStore]:
    adapter = PandaScoreAdapter(
        base_url="https://pandascore.test",
        token="test-token",
        transport=httpx.MockTransport(handler),
    )
    store = SessionArtifactStore()
    registry = ToolRegistry()
    externalizer = ToolResponseExternalizer(store)
    register_artifact_tools(registry, ArtifactReader(store), ArtifactGrepper(store))
    register_esports_tools(
        registry,
        PandaScoreNativeQueryExecutor(PandaScoreCapabilities.load(), adapter),
        EsportsSearchObservationBuilder(externalizer),
    )
    return registry, adapter, store


def test_large_search_spills_complete_logical_response_under_fresh_string_ref() -> None:
    rows = _large_rows()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=rows, request=request)

    registry, adapter, store = _registry(handler)

    async def exercise():
        try:
            first = await registry.execute(
                ToolCall(id="first", name="esports.search", arguments={"resource": "tournament"})
            )
            second = await registry.execute(
                ToolCall(id="second", name="esports.search", arguments={"resource": "tournament"})
            )
            ref = first.content["artifact_ref"]
            matches = await registry.execute(
                ToolCall(
                    id="matches-read",
                    name="artifact.read",
                    arguments={
                        "ref": ref,
                        "mode": "read",
                        "path": first.content["rows"][0]["matches"]["_artifact_path"],
                    },
                )
            )
            future = await registry.execute(
                ToolCall(
                    id="future-read",
                    name="artifact.read",
                    arguments={
                        "ref": ref,
                        "mode": "read",
                        "path": "rows.0.unknown_future_field.deep",
                    },
                )
            )
            grep = await ArtifactGrepper(store).grep(ref, "Grand final")
            return first, second, matches, future, grep
        finally:
            await adapter.aclose()

    first, second, matches, future, grep = asyncio.run(exercise())

    assert first.status == "ok"
    assert first.content["truncated"] is True
    assert first.content["artifact_ref"].startswith("artifact:tool:")
    assert first.content["artifact_ref"] != second.content["artifact_ref"]
    assert first.content["returned_rows"] == len(rows)
    assert first.content["rows"][0]["matches"] == {"_artifact_path": "rows.0.matches", "_count": 20}
    assert matches.content["value"] == rows[0]["matches"]
    assert future.content["value"] == [1, 2, 3]
    assert grep.returned == 20
    assert {match.ref for match in grep.matches} == {first.content["artifact_ref"]}


def test_small_search_stays_inline_and_unknown_ref_is_rejected() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=[{"id": 4106, "name": "The International"}],
            request=request,
        )

    registry, adapter, _ = _registry(handler)

    async def exercise():
        try:
            small = await registry.execute(
                ToolCall(id="small", name="esports.search", arguments={"resource": "league"})
            )
            unknown = await registry.execute(
                ToolCall(
                    id="unknown",
                    name="artifact.grep",
                    arguments={"ref": "artifact:tool:" + "0" * 32, "pattern": "anything"},
                )
            )
            corpus = await registry.execute(
                ToolCall(id="corpus", name="artifact.grep", arguments={"pattern": "anything"})
            )
            return small, unknown, corpus
        finally:
            await adapter.aclose()

    small, unknown, corpus = asyncio.run(exercise())

    assert small.content["artifact_ref"] is None
    assert small.content["returned_rows"] == 1
    assert small.content["rows"] == [{"id": 4106, "name": "The International"}]
    assert unknown.error is not None and unknown.error.code == "artifact_not_found"
    assert corpus.error is not None and corpus.error.code == "invalid_arguments"


def test_dynamic_ref_is_not_visible_to_a_second_session_registry() -> None:
    rows = _large_rows()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=rows, request=request)

    first_registry, first_adapter, _ = _registry(handler)
    second_registry, second_adapter, _ = _registry(handler)

    async def exercise():
        try:
            produced = await first_registry.execute(
                ToolCall(id="produce", name="esports.search", arguments={"resource": "tournament"})
            )
            return await second_registry.execute(
                ToolCall(
                    id="other-session",
                    name="artifact.read",
                    arguments={"ref": produced.content["artifact_ref"], "mode": "outline"},
                )
            )
        finally:
            await first_adapter.aclose()
            await second_adapter.aclose()

    denied = asyncio.run(exercise())

    assert denied.error is not None and denied.error.code == "artifact_not_found"
