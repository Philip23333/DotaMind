from __future__ import annotations

import asyncio
import json
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


def _call(arguments: dict[str, Any], call_id: str = "search-1") -> ToolCall:
    return ToolCall(id=call_id, name="esports.search", arguments=arguments)


def test_esports_search_tool_schema_is_compact_and_model_visible() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[], request=request)

    adapter = PandaScoreAdapter(token="test-token", transport=httpx.MockTransport(handler))
    executor = PandaScoreNativeQueryExecutor(PandaScoreCapabilities.load(), adapter)
    tool = build_esports_search_tool(
        executor,
        EsportsSearchObservationBuilder(ToolResponseExternalizer(SessionArtifactStore())),
    )
    schema = tool.schema().input_schema
    properties = schema["properties"]

    assert tool.name == "esports.search"
    assert tool.read_only is True
    assert "bounded previews with an artifact_ref" in tool.description
    assert set(properties) == {
        "resource",
        "scope",
        "filter",
        "search",
        "range",
        "sort",
        "page",
        "page_size",
    }
    assert properties["resource"]["enum"] == [
        "league",
        "serie",
        "tournament",
        "match",
        "team",
        "player",
    ]
    assert properties["scope"]["enum"] == ["all", "past", "running", "upcoming"]
    schema_text = json.dumps(schema)
    endpoint_fields = {"league_id", "serie_id", "tournament_id", "year", "tier"}
    assert not endpoint_fields & set(schema_text.split('"'))


def test_esports_search_handler_preserves_source_shaped_rows() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/dota2/tournaments"
        assert request.url.params["filter[serie_id]"] == "10828"
        assert request.url.params["filter[name]"] == "Group Stage"
        return httpx.Response(
            200,
            json=[{"id": 21545, "name": "Group Stage", "serie_id": 10828}],
            request=request,
        )

    registry, adapter = _registry(handler)

    async def exercise():
        try:
            return await registry.execute(
                _call(
                    {
                        "resource": "tournament",
                        "filter": {"serie_id": 10828, "name": "Group Stage"},
                    }
                )
            )
        finally:
            await adapter.aclose()

    result = asyncio.run(exercise())
    assert result.status == "ok"
    assert result.content == {
        "resource": "tournament",
        "scope": "all",
        "rows": [{"id": 21545, "name": "Group Stage", "serie_id": 10828}],
        "has_more": False,
        "truncated": False,
        "artifact_ref": None,
        "total_rows": None,
    }


def test_esports_search_exposes_structured_query_validation_errors() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("invalid queries must not reach HTTP")

    registry, adapter = _registry(handler)

    async def exercise():
        try:
            invalid_field = await registry.execute(
                _call({"resource": "tournament", "filter": {"league_id": 4106, "year": 2026}})
            )
            invalid_scope = await registry.execute(
                _call({"resource": "league", "scope": "running"}, call_id="scope-1")
            )
            return invalid_field, invalid_scope
        finally:
            await adapter.aclose()

    invalid_field, invalid_scope = asyncio.run(exercise())
    assert invalid_field.error is not None
    assert invalid_field.error.code == "unsupported_field"
    assert invalid_field.error.details["fields"] == ["league_id", "year"]
    assert "supported_fields" in invalid_field.error.details
    assert invalid_scope.error is not None
    assert invalid_scope.error.code == "unsupported_scope"
    assert invalid_scope.error.details["supported_scopes"] == ["all"]


def test_esports_search_sanitizes_provider_http_errors() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"secret": "test-token"}, request=request)

    registry, adapter = _registry(handler)

    async def exercise():
        try:
            return await registry.execute(_call({"resource": "league"}))
        finally:
            await adapter.aclose()

    result = asyncio.run(exercise())
    assert result.error is not None
    assert result.error.code == "provider_http_error"
    assert result.error.details == {"status_code": 500}
    assert "test-token" not in json.dumps(result.model_dump(mode="json"))


def test_registry_and_composition_expose_esports_search_without_network_calls() -> None:
    services = build_vnext_services(settings=VNextSettings())
    registry = build_vnext_registry(services)

    assert registry.get("esports.search").name == "esports.search"
    assert services.pandascore_capabilities.endpoint("match", "running")
    assert services.pandascore_native_queries is not None
    asyncio.run(services.aclose())


def test_manual_multi_call_uses_returned_source_ids_without_workflow_code() -> None:
    requests: list[tuple[str, dict[str, str]]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        params = dict(request.url.params)
        requests.append((request.url.path, params))
        if request.url.path == "/dota2/leagues":
            return httpx.Response(
                200,
                json=[{"id": 4106, "name": "The International"}],
                request=request,
            )
        if request.url.path == "/dota2/series":
            assert params["filter[league_id]"] == "4106"
            assert params["filter[year]"] == "2026"
            return httpx.Response(200, json=[{"id": 10828, "league_id": 4106}], request=request)
        assert request.url.path == "/dota2/tournaments"
        assert params["filter[serie_id]"] == "10828"
        assert params["filter[name]"] == "Group Stage"
        return httpx.Response(200, json=[{"id": 21545, "serie_id": 10828}], request=request)

    registry, adapter = _registry(handler)

    async def exercise():
        try:
            league = await registry.execute(
                _call({"resource": "league", "search": {"name": "The International"}}, "league-1")
            )
            serie = await registry.execute(
                _call(
                    {
                        "resource": "serie",
                        "filter": {"league_id": league.content["rows"][0]["id"], "year": 2026},
                    },
                    "serie-1",
                )
            )
            return await registry.execute(
                _call(
                    {
                        "resource": "tournament",
                        "filter": {
                            "serie_id": serie.content["rows"][0]["id"],
                            "name": "Group Stage",
                        },
                    },
                    "tournament-1",
                )
            )
        finally:
            await adapter.aclose()

    result = asyncio.run(exercise())
    assert result.status == "ok"
    assert result.content["rows"][0]["id"] == 21545
    assert [path for path, _ in requests] == [
        "/dota2/leagues",
        "/dota2/series",
        "/dota2/tournaments",
    ]
