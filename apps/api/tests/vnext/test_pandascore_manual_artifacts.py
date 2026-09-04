"""Static generated PandaScore manuals exposed through generic artifact tools."""

from __future__ import annotations

import asyncio

import httpx

from app.vnext.artifacts import (
    PANDASCORE_MANUAL_REFS,
    ArtifactGrepper,
    ArtifactReader,
    ManualResolver,
    SessionArtifactStore,
    ToolResponseExternalizer,
)
from app.vnext.composition import VNextSettings, build_vnext_registry, build_vnext_services
from app.vnext.llm.protocol import ToolCall
from app.vnext.providers.pandascore.adapter import PandaScoreAdapter
from app.vnext.tools.artifacts import register_artifact_tools
from app.vnext.tools.domain.esports import register_esports_tools
from app.vnext.tools.domain.esports_observation import EsportsSearchObservationBuilder
from app.vnext.tools.registry import ToolRegistry


def test_all_pandascore_manual_refs_read_generated_content() -> None:
    async def exercise() -> dict[str, str]:
        reader = ArtifactReader(SessionArtifactStore(), ManualResolver())
        results = {
            ref: (await reader.read(ref, "content")).value for ref in PANDASCORE_MANUAL_REFS
        }
        return results

    manuals = asyncio.run(exercise())

    assert set(manuals) == set(PANDASCORE_MANUAL_REFS)
    assert "`serie_id`" in manuals["manual:pandascore:tournament"]
    assert "does not support `league_id`" in manuals["manual:pandascore:tournament"]
    assert "does not support `year`" in manuals["manual:pandascore:tournament"]
    assert "`league_id`" in manuals["manual:pandascore:serie"]
    assert "`year`" in manuals["manual:pandascore:serie"]
    assert "`tournament_id`" in manuals["manual:pandascore:match"]


def test_static_manuals_work_through_registry_tools() -> None:
    async def exercise():
        services = build_vnext_services(settings=VNextSettings())
        registry = build_vnext_registry(services)
        try:
            read = await registry.execute(
                ToolCall(
                    id="manual-read",
                    name="artifact.read",
                    arguments={
                        "ref": "manual:pandascore:tournament",
                        "mode": "read",
                        "path": "content",
                    },
                )
            )
            outline = await registry.execute(
                ToolCall(
                    id="manual-outline",
                    name="artifact.read",
                    arguments={"ref": "manual:pandascore:tournament", "mode": "outline"},
                )
            )
            grep = await registry.execute(
                ToolCall(
                    id="manual-grep",
                    name="artifact.grep",
                    arguments={
                        "ref": "manual:pandascore:tournament",
                        "pattern": "does not support `league_id`",
                    },
                )
            )
            missing = await registry.execute(
                ToolCall(
                    id="manual-missing",
                    name="artifact.read",
                    arguments={
                        "ref": "manual:pandascore:hero",
                        "mode": "outline",
                    },
                )
            )
            traversal = await registry.execute(
                ToolCall(
                    id="manual-traversal",
                    name="artifact.read",
                    arguments={
                        "ref": "manual:pandascore:../README",
                        "mode": "outline",
                    },
                )
            )
            nested_traversal = await registry.execute(
                ToolCall(
                    id="manual-nested-traversal",
                    name="artifact.read",
                    arguments={
                        "ref": "manual:pandascore:../../secret",
                        "mode": "outline",
                    },
                )
            )
            return registry, read, outline, grep, missing, traversal, nested_traversal
        finally:
            await services.aclose()

    registry, read, outline, grep, missing, traversal, nested_traversal = asyncio.run(exercise())

    assert read.status == "ok"
    assert read.content["ref"] == "manual:pandascore:tournament"
    assert "does not support `league_id`" in read.content["value"]
    assert outline.status == "ok"
    assert outline.content["value"] == {"paths": [{"path": "content", "kind": "text"}]}
    assert grep.status == "ok"
    assert grep.content["matches"] == [
        {
            "ref": "manual:pandascore:tournament",
            "path": "content",
            "preview": grep.content["matches"][0]["preview"],
        }
    ]
    assert "does not support `league_id`" in grep.content["matches"][0]["preview"]
    assert missing.error is not None and missing.error.code == "artifact_not_found"
    assert traversal.error is not None and traversal.error.code == "artifact_not_found"
    assert nested_traversal.error is not None
    assert nested_traversal.error.code == "artifact_not_found"
    assert "esports.search" not in {tool.name for tool in registry.schemas()}


def test_manual_read_and_legacy_esports_search_can_share_internal_services() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/dota2/tournaments"
        assert request.url.params["filter[serie_id]"] == "10828"
        return httpx.Response(200, json=[{"id": 21545, "serie_id": 10828}], request=request)

    adapter = PandaScoreAdapter(
        base_url="https://pandascore.test",
        token="test-token",
        transport=httpx.MockTransport(handler),
    )

    async def exercise():
        services = build_vnext_services(settings=VNextSettings(), pandascore=adapter)
        store = SessionArtifactStore()
        registry = ToolRegistry()
        register_artifact_tools(
            registry,
            ArtifactReader(store, ManualResolver()),
            ArtifactGrepper(store, ManualResolver()),
        )
        register_esports_tools(
            registry,
            services.pandascore_native_queries,
            EsportsSearchObservationBuilder(ToolResponseExternalizer(store)),
        )
        try:
            manual = await registry.execute(
                ToolCall(
                    id="manual",
                    name="artifact.read",
                    arguments={
                        "ref": "manual:pandascore:tournament",
                        "mode": "read",
                        "path": "content",
                    },
                )
            )
            search = await registry.execute(
                ToolCall(
                    id="search",
                    name="esports.search",
                    arguments={"resource": "tournament", "filter": {"serie_id": 10828}},
                )
            )
            return manual, search
        finally:
            await services.aclose()

    manual, search = asyncio.run(exercise())

    assert manual.status == "ok"
    assert "`serie_id`" in manual.content["value"]
    assert search.status == "ok"
    assert search.content["rows"] == [{"id": 21545, "serie_id": 10828}]
