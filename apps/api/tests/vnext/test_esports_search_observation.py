"""Focused contracts for bounded esports.search observations."""

from __future__ import annotations

import asyncio
from typing import Any

import httpx

from app.vnext.artifacts import ArtifactGrepper, ArtifactReader, ArtifactRef, MemoryArtifactStore
from app.vnext.llm.protocol import ToolCall
from app.vnext.providers.pandascore.adapter import PandaScoreAdapter
from app.vnext.providers.pandascore.capabilities import PandaScoreCapabilities
from app.vnext.providers.pandascore.query import PandaScoreNativeQueryExecutor
from app.vnext.tools.domain.esports import register_esports_tools
from app.vnext.tools.domain.esports_observation import EsportsSearchObservationBuilder
from app.vnext.tools.registry import ToolRegistry


def _large_tournaments() -> list[dict[str, Any]]:
    return [
        {
            "id": tournament_id,
            "name": name,
            "serie_id": 10828,
            "league_id": 4106,
            "tier": "s",
            "matches": [
                {
                    "id": tournament_id * 100 + match_index,
                    "name": f"Grand final detail {match_index}",
                    "streams_list": [{"embed_url": "https://example.test/" + "x" * 300}],
                }
                for match_index in range(20)
            ],
            "teams": [{"id": team_id, "name": f"Team {team_id}"} for team_id in range(16)],
            "expected_roster": [{"name": "Player " + "y" * 200} for _ in range(10)],
            "custom_unknown_field": {"deep": {"x": [1, 2, 3]}},
        }
        for tournament_id, name in [
            (21698, "Playoffs"),
            (21696, "Elimination Round"),
            (21545, "Group Stage"),
        ]
    ]


def _registry(
    handler: httpx.MockTransport | Any,
    store: MemoryArtifactStore,
) -> tuple[ToolRegistry, PandaScoreAdapter]:
    adapter = PandaScoreAdapter(
        base_url="https://pandascore.test",
        token="test-token",
        transport=httpx.MockTransport(handler),
    )
    registry = ToolRegistry()
    register_esports_tools(
        registry,
        PandaScoreNativeQueryExecutor(PandaScoreCapabilities.load(), adapter),
        EsportsSearchObservationBuilder(store),
    )
    return registry, adapter


def _refs(store: MemoryArtifactStore) -> list[ArtifactRef]:
    async def collect() -> list[ArtifactRef]:
        return [ref async for ref in store.iter_refs()]

    return asyncio.run(collect())


def test_large_result_is_one_recoverable_bounded_observation() -> None:
    rows = _large_tournaments()
    store = MemoryArtifactStore()

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/dota2/tournaments"
        assert request.url.params["filter[serie_id]"] == "10828"
        assert request.url.params["page[number]"] == "1"
        assert request.url.params["page[size]"] == "50"
        return httpx.Response(200, json=rows, request=request)

    registry, adapter = _registry(handler, store)

    async def exercise():
        try:
            result = await registry.execute(
                ToolCall(
                    id="large",
                    name="esports.search",
                    arguments={
                        "resource": "tournament",
                        "filter": {"serie_id": 10828},
                        "page_size": 50,
                    },
                )
            )
            assert result.status == "ok"
            ref = ArtifactRef.model_validate(result.content["artifact_ref"])
            matches_path = result.content["rows"][2]["matches"]["_artifact_path"]
            nested = await ArtifactReader(store).read(ref, matches_path)
            unknown = await ArtifactReader(store).read(
                ref,
                "result.rows.2.custom_unknown_field.deep.x",
            )
            grep = await ArtifactGrepper(store).grep(
                "Grand final detail 0",
                artifact_types=["esports_search_result"],
            )
            return result, ref, matches_path, nested, unknown, grep
        finally:
            await adapter.aclose()

    result, ref, matches_path, nested, unknown, grep = asyncio.run(exercise())

    assert result.content["truncated"] is True
    assert result.content["total_rows"] == 3
    assert result.content["artifact_ref"] == ref.model_dump(mode="json")
    assert [row["name"] for row in result.content["rows"]] == [
        "Playoffs",
        "Elimination Round",
        "Group Stage",
    ]
    group_stage = result.content["rows"][2]
    assert group_stage["id"] == 21545
    assert group_stage["serie_id"] == 10828
    assert group_stage["matches"] == {
        "_artifact_path": "result.rows.2.matches",
        "_count": 20,
    }
    assert group_stage["teams"] == {
        "_artifact_path": "result.rows.2.teams",
        "_count": 16,
    }
    assert group_stage["expected_roster"] == {
        "_artifact_path": "result.rows.2.expected_roster",
        "_count": 10,
    }
    assert matches_path == "result.rows.2.matches"
    assert nested.value == rows[2]["matches"]
    assert unknown.value == [1, 2, 3]
    assert grep.returned == 3
    assert {match.ref for match in grep.matches} == {ref}
    assert _refs(store) == [ref]


def test_small_result_stays_inline_without_creating_an_artifact() -> None:
    store = MemoryArtifactStore()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=[{"id": 4106, "name": "The International"}],
            request=request,
        )

    registry, adapter = _registry(handler, store)

    async def exercise():
        try:
            return await registry.execute(
                ToolCall(id="small", name="esports.search", arguments={"resource": "league"})
            )
        finally:
            await adapter.aclose()

    result = asyncio.run(exercise())

    assert result.status == "ok"
    assert result.content["rows"] == [{"id": 4106, "name": "The International"}]
    assert result.content["truncated"] is False
    assert result.content["artifact_ref"] is None
    assert result.content["total_rows"] is None
    assert _refs(store) == []


class _FailingStore(MemoryArtifactStore):
    async def put(self, ref, artifact) -> None:  # type: ignore[no-untyped-def]
        raise RuntimeError("store unavailable")


def test_large_result_returns_artifact_error_when_persistence_fails() -> None:
    rows = _large_tournaments()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=rows, request=request)

    registry, adapter = _registry(handler, _FailingStore())

    async def exercise():
        try:
            return await registry.execute(
                ToolCall(id="failing", name="esports.search", arguments={"resource": "tournament"})
            )
        finally:
            await adapter.aclose()

    result = asyncio.run(exercise())

    assert result.status == "error"
    assert result.error is not None
    assert result.error.code == "artifact_error"
    assert result.error.details == {
        "source": "pandascore",
        "resource": "tournament",
        "scope": "all",
    }


def test_query_identity_is_stable_for_the_same_search_input() -> None:
    rows = _large_tournaments()
    store = MemoryArtifactStore()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=rows, request=request)

    registry, adapter = _registry(handler, store)

    async def exercise():
        try:
            first = await registry.execute(
                ToolCall(id="first", name="esports.search", arguments={"resource": "tournament"})
            )
            second = await registry.execute(
                ToolCall(id="second", name="esports.search", arguments={"resource": "tournament"})
            )
            return first, second
        finally:
            await adapter.aclose()

    first, second = asyncio.run(exercise())

    assert first.content["artifact_ref"] == second.content["artifact_ref"]
    assert len(_refs(store)) == 1
