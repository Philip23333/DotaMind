"""Default model-visible vNext tool surface contracts."""

import asyncio
from datetime import datetime, timezone

from app.vnext.artifacts import (
    GameDetailArtifact,
    MemoryArtifactStore,
    SourceDocumentArtifact,
    game_detail_artifact_ref,
    source_document_artifact_ref,
)
from app.vnext.composition import VNextSettings, build_vnext_registry, build_vnext_services
from app.vnext.llm.protocol import ToolCall


def test_default_registry_exposes_only_current_capabilities() -> None:
    registry = build_vnext_registry(settings=VNextSettings())

    tool_names = {tool.name for tool in registry.schemas()}
    assert tool_names == {
        "artifact.grep",
        "artifact.read",
        "esports.search",
        "game.detail",
    }
    assert not tool_names.intersection(
        {
            "artifact.search",
            "matches.get_detail",
            "teams.search",
            "teams.get_detail",
            "players.search",
            "players.get_detail",
        }
    )


def test_default_artifact_tools_read_and_grep_current_source_documents() -> None:
    async def exercise() -> None:
        store = MemoryArtifactStore()
        services = build_vnext_services(settings=VNextSettings(), artifact_store=store)
        registry = build_vnext_registry(services)
        fetched_at = datetime(2026, 8, 31, tzinfo=timezone.utc)
        source_ref = source_document_artifact_ref("pandascore", "team", "team-spirit")
        detail_ref = game_detail_artifact_ref(8960577698)
        await store.put(
            source_ref,
            SourceDocumentArtifact(
                source="pandascore",
                kind="team",
                fetched_at=fetched_at,
                facts={"name": "Team Spirit", "marker": "source-document-marker"},
            ),
        )
        await store.put(
            detail_ref,
            GameDetailArtifact(
                source="opendota",
                valve_game_id=8960577698,
                fetched_at=fetched_at,
                facts={"radiant_name": "game-detail-marker"},
            ),
        )

        unknown = await registry.execute(
            ToolCall(
                id="legacy-search",
                name="artifact.search",
                arguments={"artifact_type": "game_summary", "valve_match_ids": [8960577698]},
            )
        )
        source_read = await registry.execute(
            ToolCall(
                id="source-read",
                name="artifact.read",
                arguments={"ref": source_ref.model_dump(), "path": "facts.name"},
            )
        )
        detail_read = await registry.execute(
            ToolCall(
                id="detail-read",
                name="artifact.read",
                arguments={"ref": detail_ref.model_dump(), "path": "facts.radiant_name"},
            )
        )
        source_grep = await registry.execute(
            ToolCall(
                id="source-grep",
                name="artifact.grep",
                arguments={"pattern": "source-document-marker"},
            )
        )
        detail_grep = await registry.execute(
            ToolCall(
                id="detail-grep",
                name="artifact.grep",
                arguments={"pattern": "game-detail-marker"},
            )
        )

        assert unknown.status == "error"
        assert unknown.error is not None and unknown.error.code == "unknown_tool"
        assert source_read.status == "ok"
        assert source_read.content["value"] == "Team Spirit"
        assert detail_read.status == "ok"
        assert detail_read.content["value"] == "game-detail-marker"
        assert source_grep.status == "ok"
        assert any(
            match["ref"] == source_ref.model_dump() for match in source_grep.content["matches"]
        )
        assert detail_grep.status == "ok"
        assert any(
            match["ref"] == detail_ref.model_dump() for match in detail_grep.content["matches"]
        )

    asyncio.run(exercise())
