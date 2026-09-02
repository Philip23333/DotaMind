"""Static generated PandaScore manuals exposed through generic artifact tools."""

from __future__ import annotations

import asyncio

import httpx

from app.vnext.artifacts import (
    PANDASCORE_MANUAL_REFS,
    ArtifactReader,
    ManualResolver,
    SessionArtifactStore,
)
from app.vnext.composition import VNextSettings, build_vnext_registry, build_vnext_services
from app.vnext.llm.protocol import ToolCall
from app.vnext.providers.pandascore.adapter import PandaScoreAdapter


def test_all_pandascore_manual_refs_read_generated_content() -> None:
    async def exercise() -> dict[str, str]:
        reader = ArtifactReader(SessionArtifactStore(), ManualResolver())
        results = {
            ref: (await reader.read(ref)).value for ref in PANDASCORE_MANUAL_REFS
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
                    arguments={"ref": "manual:pandascore:tournament"},
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
                    arguments={"ref": "manual:pandascore:hero"},
                )
            )
            traversal = await registry.execute(
                ToolCall(
                    id="manual-traversal",
                    name="artifact.read",
                    arguments={"ref": "manual:pandascore:../README"},
                )
            )
            nested_traversal = await registry.execute(
                ToolCall(
                    id="manual-nested-traversal",
                    name="artifact.read",
                    arguments={"ref": "manual:pandascore:../../secret"},
                )
            )
            return registry, read, grep, missing, traversal, nested_traversal
        finally:
            await services.aclose()

    registry, read, grep, missing, traversal, nested_traversal = asyncio.run(exercise())

    assert read.status == "ok"
    assert read.content["ref"] == "manual:pandascore:tournament"
    assert "does not support `league_id`" in read.content["value"]
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
    assert "manual:pandascore:index" in registry.get("esports.search").description


def test_manual_read_and_esports_search_share_one_composed_registry() -> None:
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
        registry = build_vnext_registry(services)
        try:
            manual = await registry.execute(
                ToolCall(
                    id="manual",
                    name="artifact.read",
                    arguments={"ref": "manual:pandascore:tournament"},
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
