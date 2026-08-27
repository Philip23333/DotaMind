from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone

import pytest

from app.vnext.artifacts import (
    ArtifactPathNotFoundError,
    ArtifactReader,
    ArtifactReadValidationError,
    ArtifactSearcher,
    MemoryArtifactStore,
    game_summary_artifact_ref,
)
from app.vnext.artifacts.game_summary_v4 import GameSummaryArtifactV4
from app.vnext.composition import build_vnext_registry
from app.vnext.llm.protocol import ToolCall
from app.vnext.tools.artifacts.retrieval import ArtifactReadInput, ArtifactSearchInput
from tests.vnext.phase2_support import fixture_services, fixture_vnext_services


def _artifact() -> GameSummaryArtifactV4:
    return GameSummaryArtifactV4(
        game={
            "valve_match_id": 8123456789,
            "start_time": datetime(2026, 8, 26, 12, tzinfo=timezone.utc),
        },
        teams={},
        players=[
            {
                "identity": {},
                "side": "radiant",
                "player_slot": 0,
                "hero": {"id": 1},
                "items": {"inventory": [{"slot": 0}]},
                "purchase_history": [
                    {"time_seconds": 10, "item_id": 1},
                    {"time_seconds": 20, "item_id": 2},
                ],
            }
        ],
    )


def test_search_deduplicates_in_input_order_and_only_checks_existence() -> None:
    store = MemoryArtifactStore()
    ref = game_summary_artifact_ref(8123456789)
    store.put(ref, _artifact())
    searcher = ArtifactSearcher(store)

    result = searcher.search("game_summary", [8123456789, 1, 8123456789, 2, 1])

    assert result.refs == [ref]
    assert result.missing_valve_match_ids == [1, 2]


def test_reader_outline_is_bounded_and_serializes_datetime() -> None:
    store = MemoryArtifactStore()
    ref = game_summary_artifact_ref(8123456789)
    artifact = _artifact()
    store.put(ref, artifact)
    reader = ArtifactReader(store)

    result = reader.read(ref)

    assert result.path is None
    assert result.offset is None
    assert result.limit is None
    assert result.total is None
    assert result.truncated is False
    assert result.value == {
        "artifact_type": "game_summary",
        "schema_version": "4",
        "sections": {
            "game": {"kind": "object"},
            "teams": {"kind": "object"},
            "players": {"kind": "collection", "count": 1},
            "draft": {"kind": "object"},
        },
    }
    json.dumps(result.model_dump(mode="json"))
    assert reader.read(ref, "game.start_time").value == "2026-08-26T12:00:00Z"


def test_reader_traverses_objects_lists_and_preserves_null_values() -> None:
    store = MemoryArtifactStore()
    ref = game_summary_artifact_ref(8123456789)
    store.put(ref, _artifact())
    reader = ArtifactReader(store)

    assert reader.read(ref, "game.valve_match_id").value == 8123456789
    assert reader.read(ref, "players.0.items.inventory.0.id").value is None
    assert reader.read(ref, "players.0.purchase_history", offset=1, limit=1).value == [
        {
            "time_seconds": 20,
            "item_id": 2,
            "item_name_en": None,
            "item_name_zh": None,
        }
    ]
    paged = reader.read(ref, "players.0.purchase_history", offset=0, limit=1)
    assert paged.offset == 0
    assert paged.limit == 1
    assert paged.total == 2
    assert paged.truncated is True


@pytest.mark.parametrize(
    "path",
    ["missing", "players.1", "players.name", "players.0.side.value", "players..side", "-1"],
)
def test_reader_uses_one_error_for_invalid_paths(path: str) -> None:
    store = MemoryArtifactStore()
    ref = game_summary_artifact_ref(8123456789)
    store.put(ref, _artifact())

    with pytest.raises(ArtifactPathNotFoundError):
        ArtifactReader(store).read(ref, path)


def test_reader_rejects_pagination_for_outline_or_non_list_values() -> None:
    store = MemoryArtifactStore()
    ref = game_summary_artifact_ref(8123456789)
    store.put(ref, _artifact())
    reader = ArtifactReader(store)

    with pytest.raises(ArtifactReadValidationError):
        reader.read(ref, offset=0, pagination_requested=True)
    with pytest.raises(ArtifactReadValidationError):
        reader.read(ref, "game", limit=1)
    with pytest.raises(ArtifactReadValidationError):
        reader.read(ref, "game", limit=50, pagination_requested=True)
    with pytest.raises(ArtifactReadValidationError):
        reader.read(ref, "players", limit=101)


def test_registry_tool_chain_produces_searches_and_reads_one_artifact() -> None:
    competition_service, match_service, panda, opendota = fixture_services()
    services = fixture_vnext_services(competition_service, match_service, panda, opendota)

    registry = build_vnext_registry(services)

    async def exercise():
        search = await registry.execute(
            ToolCall(
                id="match-search",
                name="matches.search",
                arguments={"query": "Round 2", "time_scope": "recent"},
            )
        )
        assert opendota.construction_calls == []
        match_ref = search.content["candidates"][0]["ref"]["value"]
        detail = await registry.execute(
            ToolCall(
                id="match-detail",
                name="matches.get_detail",
                arguments={"match_ref": {"value": match_ref}},
            )
        )
        valve_match_id = detail.content["games"][0]["valve_match_id"]
        found = await registry.execute(
            ToolCall(
                id="artifact-search",
                name="artifact.search",
                arguments={
                    "artifact_type": "game_summary",
                    "valve_match_ids": [valve_match_id, 999999, valve_match_id],
                },
            )
        )
        artifact_ref = found.content["refs"][0]
        read = await registry.execute(
            ToolCall(
                id="artifact-read",
                name="artifact.read",
                arguments={"ref": artifact_ref, "path": "game"},
            )
        )
        return search, detail, found, read

    search, detail, found, read = asyncio.run(exercise())

    assert search.status == detail.status == found.status == read.status == "ok"
    assert detail.content["games"][0]["valve_match_id"] == 40001
    assert found.content["missing_valve_match_ids"] == [999999]
    assert read.content["path"] == "game"
    assert read.content["value"]["valve_match_id"] == 40001
    assert read.content["offset"] is None
    assert opendota.construction_calls == [40001]


def test_unresolved_games_do_not_trigger_artifact_production() -> None:
    competition_service, match_service, panda, opendota = fixture_services(
        resolution_available=False
    )
    services = fixture_vnext_services(competition_service, match_service, panda, opendota)

    registry = build_vnext_registry(services)

    async def exercise():
        search = await registry.execute(
            ToolCall(
                id="match-search",
                name="matches.search",
                arguments={"query": "Round 2", "time_scope": "recent"},
            )
        )
        match_ref = search.content["candidates"][0]["ref"]["value"]
        return await registry.execute(
            ToolCall(
                id="match-detail",
                name="matches.get_detail",
                arguments={"match_ref": {"value": match_ref}},
            )
        )

    result = asyncio.run(exercise())

    assert result.status == "ok"
    assert all(game["valve_match_id"] is None for game in result.content["games"])
    assert opendota.construction_calls == []


def test_each_resolved_game_is_produced_and_stored() -> None:
    competition_service, match_service, panda, opendota = fixture_services()
    services = fixture_vnext_services(competition_service, match_service, panda, opendota)

    registry = build_vnext_registry(services)

    async def exercise():
        search = await registry.execute(
            ToolCall(
                id="match-search",
                name="matches.search",
                arguments={"query": "Grand Final", "time_scope": "recent"},
            )
        )
        match_ref = search.content["candidates"][0]["ref"]["value"]
        return await registry.execute(
            ToolCall(
                id="match-detail",
                name="matches.get_detail",
                arguments={"match_ref": {"value": match_ref}},
            )
        )

    result = asyncio.run(exercise())

    assert result.status == "ok"
    assert [game["valve_match_id"] for game in result.content["games"]] == [40002, 40003, 40004]
    assert opendota.construction_calls == [40002, 40003, 40004]
    assert all(
        services.artifact_store.exists(game_summary_artifact_ref(match_id))
        for match_id in (40002, 40003, 40004)
    )


def test_production_failure_fails_get_detail_tool() -> None:
    competition_service, match_service, panda, opendota = fixture_services(
        detail_available=False
    )
    services = fixture_vnext_services(competition_service, match_service, panda, opendota)

    registry = build_vnext_registry(services)

    async def exercise():
        search = await registry.execute(
            ToolCall(
                id="match-search",
                name="matches.search",
                arguments={"query": "Round 2", "time_scope": "recent"},
            )
        )
        match_ref = search.content["candidates"][0]["ref"]["value"]
        return await registry.execute(
            ToolCall(
                id="match-detail",
                name="matches.get_detail",
                arguments={"match_ref": {"value": match_ref}},
            )
        )

    result = asyncio.run(exercise())

    assert result.status == "error"
    assert result.error is not None and result.error.code == "tool_execution_error"
    assert opendota.construction_calls == [40001]


def test_artifact_read_missing_path_is_a_stable_tool_error() -> None:
    competition_service, match_service, panda, opendota = fixture_services()
    services = fixture_vnext_services(competition_service, match_service, panda, opendota)
    ref = game_summary_artifact_ref(8123456789)
    services.artifact_store.put(ref, _artifact())

    registry = build_vnext_registry(services)
    result = asyncio.run(
        registry.execute(
            ToolCall(
                id="missing-artifact-path",
                name="artifact.read",
                arguments={
                    "ref": ref.model_dump(),
                    "path": "players.1",
                },
            )
        )
    )

    assert result.status == "error"
    assert result.error is not None and result.error.code == "artifact_path_not_found"


def test_artifact_read_missing_ref_is_an_explicit_tool_error() -> None:
    competition_service, match_service, panda, opendota = fixture_services()
    services = fixture_vnext_services(competition_service, match_service, panda, opendota)

    registry = build_vnext_registry(services)
    result = asyncio.run(
        registry.execute(
            ToolCall(
                id="missing-artifact",
                name="artifact.read",
                arguments={
                    "ref": {
                        "id": "game_summary:4:999999",
                        "artifact_type": "game_summary",
                        "schema_version": "4",
                    },
                    "path": "game",
                },
            )
        )
    )

    assert result.status == "error"
    assert result.error is not None and result.error.code == "artifact_not_found"


def test_tool_input_contracts_bound_search_and_read() -> None:
    with pytest.raises(ValueError):
        ArtifactSearchInput.model_validate(
            {"artifact_type": "game_summary", "valve_match_ids": list(range(101))}
        )
    with pytest.raises(ValueError):
        ArtifactReadInput.model_validate(
            {
                "ref": {
                    "id": "game_summary:4:1",
                    "artifact_type": "game_summary",
                    "schema_version": "4",
                },
                "limit": 101,
            }
        )
