from __future__ import annotations

import asyncio
from typing import Any

import httpx

from app.vnext.artifacts import SessionArtifactStore, ToolResponseExternalizer
from app.vnext.composition import VNextSettings, build_vnext_registry, build_vnext_services
from app.vnext.llm.protocol import ToolCall
from app.vnext.providers.pandascore.adapter import PandaScoreAdapter
from app.vnext.providers.pandascore.capabilities import PandaScoreCapabilities
from app.vnext.providers.pandascore.query import PandaScoreNativeQueryExecutor
from app.vnext.tools.domain.esports import build_esports_search_tool, register_esports_tools
from app.vnext.tools.domain.esports_observation import EsportsSearchObservationBuilder
from app.vnext.tools.domain.esports_resources import (
    LeagueSearchInput,
    MatchSearchInput,
    build_esports_league_search_tool,
    build_esports_match_search_tool,
)
from app.vnext.tools.registry import ToolRegistry


def _registry(handler) -> tuple[ToolRegistry, PandaScoreAdapter]:
    adapter = PandaScoreAdapter(
        base_url="https://pandascore.test",
        token="test-token",
        transport=httpx.MockTransport(handler),
    )
    registry = ToolRegistry()
    executor = PandaScoreNativeQueryExecutor(PandaScoreCapabilities.load(), adapter)
    register_esports_tools(
        registry,
        executor,
        EsportsSearchObservationBuilder(ToolResponseExternalizer(SessionArtifactStore())),
    )
    return registry, adapter


def _call(name: str, arguments: dict[str, Any], call_id: str = "search-1") -> ToolCall:
    return ToolCall(id=call_id, name=name, arguments=arguments)


def test_generic_esports_search_is_only_a_fallback_for_unsplit_resources() -> None:
    adapter = PandaScoreAdapter(token="test-token", transport=httpx.MockTransport(lambda r: httpx.Response(200, json=[], request=r)))
    executor = PandaScoreNativeQueryExecutor(PandaScoreCapabilities.load(), adapter)
    tool = build_esports_search_tool(
        executor,
        EsportsSearchObservationBuilder(ToolResponseExternalizer(SessionArtifactStore())),
    )
    schema = tool.schema().input_schema

    assert tool.name == "esports.search"
    assert schema["properties"]["resource"]["enum"] == [
        "serie",
        "tournament",
        "team",
        "player",
    ]
    assert "Temporary generic fallback" in tool.description
    asyncio.run(adapter.aclose())


def test_league_search_schema_is_resource_shaped_and_explicit() -> None:
    adapter = PandaScoreAdapter(token="test-token", transport=httpx.MockTransport(lambda r: httpx.Response(200, json=[], request=r)))
    executor = PandaScoreNativeQueryExecutor(PandaScoreCapabilities.load(), adapter)
    tool = build_esports_league_search_tool(
        executor,
        EsportsSearchObservationBuilder(ToolResponseExternalizer(SessionArtifactStore())),
    )
    schema = tool.schema().input_schema
    filter_schema = schema["$defs"]["LeagueFilter"]["properties"]
    search_schema = schema["$defs"]["LeagueTextSearch"]["properties"]

    assert tool.name == "esports.league.search"
    assert set(schema["properties"]) == {"filter", "search", "range", "sort", "page", "page_size"}
    assert set(filter_schema) == {"id", "modified_at", "name", "slug", "url"}
    assert set(search_schema) == {"name", "slug", "url"}
    assert "year" not in filter_schema
    assert "The International 2026" in tool.description
    asyncio.run(adapter.aclose())


def test_match_search_schema_exposes_native_relations_and_status() -> None:
    adapter = PandaScoreAdapter(token="test-token", transport=httpx.MockTransport(lambda r: httpx.Response(200, json=[], request=r)))
    executor = PandaScoreNativeQueryExecutor(PandaScoreCapabilities.load(), adapter)
    tool = build_esports_match_search_tool(
        executor,
        EsportsSearchObservationBuilder(ToolResponseExternalizer(SessionArtifactStore())),
    )
    schema = tool.schema().input_schema
    filter_schema = schema["$defs"]["MatchFilter"]["properties"]

    assert tool.name == "esports.match.search"
    assert schema["properties"]["scope"]["enum"] == ["all", "past", "running", "upcoming"]
    assert {"league_id", "serie_id", "tournament_id", "opponent_id", "finished", "status"} <= set(filter_schema)
    assert "not equivalent to finished=true" in filter_schema["finished"]["description"]
    assert "narrowest known" in tool.description
    asyncio.run(adapter.aclose())


def test_resource_tools_inject_resource_and_preserve_native_query_execution() -> None:
    requests: list[tuple[str, dict[str, str]]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        params = dict(request.url.params)
        requests.append((request.url.path, params))
        if request.url.path == "/dota2/leagues":
            assert params["search[name]"] == "The International"
            return httpx.Response(200, json=[{"id": 4106, "name": "The International"}], request=request)
        assert request.url.path == "/dota2/matches/past"
        assert params["filter[league_id]"] == "4106"
        assert params["filter[finished]"] == "true"
        assert params["sort"] == "-begin_at"
        return httpx.Response(200, json=[{"id": 1, "league_id": 4106, "status": "finished"}], request=request)

    registry, adapter = _registry(handler)

    async def exercise():
        try:
            league = await registry.execute(
                _call(
                    "esports.league.search",
                    {"search": {"name": "The International"}, "page_size": 5},
                    "league-1",
                )
            )
            match = await registry.execute(
                _call(
                    "esports.match.search",
                    {
                        "scope": "past",
                        "filter": {"league_id": 4106, "finished": True},
                        "sort": ["-begin_at"],
                        "page_size": 5,
                    },
                    "match-1",
                )
            )
            return league, match
        finally:
            await adapter.aclose()

    league, match = asyncio.run(exercise())
    assert league.status == "ok"
    assert league.content["resource"] == "league"
    assert match.status == "ok"
    assert match.content["resource"] == "match"
    assert [path for path, _ in requests] == ["/dota2/leagues", "/dota2/matches/past"]


def test_generic_fallback_still_executes_unsplit_resources() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/dota2/tournaments"
        assert request.url.params["filter[serie_id]"] == "10828"
        return httpx.Response(200, json=[{"id": 21545, "serie_id": 10828}], request=request)

    registry, adapter = _registry(handler)

    async def exercise():
        try:
            return await registry.execute(
                _call("esports.search", {"resource": "tournament", "filter": {"serie_id": 10828}})
            )
        finally:
            await adapter.aclose()

    result = asyncio.run(exercise())
    assert result.status == "ok"
    assert result.content["rows"][0]["id"] == 21545


def test_default_composition_exposes_two_typed_resource_tools_and_fallback() -> None:
    services = build_vnext_services(settings=VNextSettings())
    registry = build_vnext_registry(services)

    assert registry.get("esports.league.search").name == "esports.league.search"
    assert registry.get("esports.match.search").name == "esports.match.search"
    assert registry.get("esports.search").name == "esports.search"
    asyncio.run(services.aclose())


def test_typed_schema_rejects_cross_resource_fields_before_http() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("invalid arguments must not reach HTTP")

    registry, adapter = _registry(handler)

    async def exercise():
        try:
            league = await registry.execute(
                _call("esports.league.search", {"filter": {"year": 2026}}, "bad-league")
            )
            match = await registry.execute(
                _call("esports.match.search", {"filter": {"tier": "s"}}, "bad-match")
            )
            return league, match
        finally:
            await adapter.aclose()

    league, match = asyncio.run(exercise())
    assert league.error is not None and league.error.code == "invalid_arguments"
    assert match.error is not None and match.error.code == "invalid_arguments"
