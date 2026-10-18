from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from typing import Any

from app.vnext.artifacts import (
    ArtifactBackedToolResultProcessor,
    SessionArtifactStore,
    ToolResponseExternalizer,
)
from app.vnext.artifacts.externalize import serialized_size
from app.vnext.capabilities.esports.game_resolution import (
    EsportsGameResolutionResult,
    EsportsGameResolveInput,
)
from app.vnext.capabilities.esports.game_resolution_continuation import (
    GameResolutionContinuation,
)
from app.vnext.composition import VNextSettings, build_vnext_registry
from app.vnext.llm.protocol import ToolCall
from app.vnext.tools.errors import StructuredToolError
from app.vnext.tools.esports.game_resolution import (
    GAME_RESOLUTION_DESCRIPTION,
    register_game_resolution_tool,
)
from app.vnext.tools.registry import ToolRegistry


def _result(*, status: str = "resolved", data: dict[str, Any] | None = None):
    return EsportsGameResolutionResult(
        status=status,
        game_position=4,
        valve_game_id=9_040_578_015 if status == "resolved" else None,
        method="inferred_cross_source" if status == "resolved" else None,
        selection_basis="verified_identity" if status == "resolved" else None,
        reason=None if status == "resolved" else "evidence_insufficient",
        providers=["pandascore", "opendota"],
        retrieved_at=datetime(2026, 10, 14, 8, 0, tzinfo=UTC),
        data=data or {"complete_evidence": True},
    )


def _processor(store: SessionArtifactStore, *, observation_max_bytes: int = 35_840):
    return ArtifactBackedToolResultProcessor(
        ToolResponseExternalizer(store, inline_max_bytes=12_288),
        observation_max_bytes=observation_max_bytes,
    )


def _call(arguments: dict[str, Any]) -> ToolCall:
    return ToolCall(
        id="resolve-call",
        name="esports.game.resolve",
        arguments=arguments,
    )


def test_tool_schema_exposes_only_artifact_continuation_fields() -> None:
    registry = ToolRegistry()

    async def resolve(_request: EsportsGameResolveInput) -> EsportsGameResolutionResult:
        return _result()

    register_game_resolution_tool(registry, resolve)
    schema = registry.schemas()[0].model_dump(mode="json")
    parameters = schema["input_schema"]["properties"]

    assert schema["name"] == "esports.game.resolve"
    assert set(parameters) == {"match_artifact_ref", "match_path", "game_position"}
    assert parameters["match_path"]["pattern"] == r"^items\.[0-9]+$"
    assert "match_id" not in json.dumps(schema)
    assert "whole-Match consistency" in GAME_RESOLUTION_DESCRIPTION


def test_small_resolution_result_is_inline_with_complete_artifact() -> None:
    store = SessionArtifactStore()
    registry = ToolRegistry(result_processor=_processor(store))
    expected = _result()
    calls: list[EsportsGameResolveInput] = []

    async def resolve(request: EsportsGameResolveInput) -> EsportsGameResolutionResult:
        calls.append(request)
        return expected

    register_game_resolution_tool(registry, resolve)
    result = asyncio.run(
        registry.execute(
            _call(
                {
                    "match_artifact_ref": "artifact:tool:" + "a" * 32,
                    "match_path": "items.0",
                    "game_position": 4,
                }
            )
        )
    )

    assert result.status == "ok"
    assert result.content["externalized"] is True
    assert result.content["value"]["status"] == "resolved"
    assert result.content["value"]["game_position"] == 4
    assert result.content["value"]["valve_game_id"] == 9_040_578_015
    assert calls[0].game_position == 4
    ref = result.content["artifact_ref"]
    assert asyncio.run(store.get(ref)) == expected.model_dump(mode="json")
    assert asyncio.run(store.get_source_tool(ref)) == "esports.game.resolve"
    assert len(store._documents) == 1


def test_large_resolution_result_is_bounded_but_artifact_is_complete() -> None:
    store = SessionArtifactStore()
    budget = 512
    registry = ToolRegistry(result_processor=_processor(store, observation_max_bytes=budget))
    expected = _result(data={"large_evidence": "x" * 40_000})

    async def resolve(_request: EsportsGameResolveInput) -> EsportsGameResolutionResult:
        return expected

    register_game_resolution_tool(registry, resolve)
    result = asyncio.run(
        registry.execute(
            _call(
                {
                    "match_artifact_ref": "artifact:tool:" + "b" * 32,
                    "match_path": "items.1",
                    "game_position": 1,
                }
            )
        )
    )

    assert result.status == "ok"
    assert serialized_size(result.content) <= budget
    observed = result.content["value"]
    assert observed["status"] == "resolved"
    assert observed["game_position"] == 4
    assert observed["valve_game_id"] == 9_040_578_015
    assert observed["reason"] is None
    ref = result.content["artifact_ref"]
    stored = asyncio.run(store.get(ref))
    assert stored == expected.model_dump(mode="json")
    assert stored["data"]["large_evidence"] == "x" * 40_000
    assert len(store._documents) == 1


def test_unresolved_result_and_structured_service_error_keep_semantics() -> None:
    store = SessionArtifactStore()
    registry = ToolRegistry(result_processor=_processor(store))

    async def unresolved(_request: EsportsGameResolveInput) -> EsportsGameResolutionResult:
        return _result(status="unresolved")

    register_game_resolution_tool(registry, unresolved)
    result = asyncio.run(
        registry.execute(
            _call(
                {
                    "match_artifact_ref": "artifact:tool:" + "c" * 32,
                    "match_path": "items.0",
                    "game_position": 4,
                }
            )
        )
    )
    assert result.status == "ok"
    assert result.content["value"]["status"] == "unresolved"
    assert result.content["value"]["reason"] == "evidence_insufficient"

    error = StructuredToolError("provider_timeout", "upstream timeout")
    error_registry = ToolRegistry(result_processor=_processor(SessionArtifactStore()))

    async def fail(_request: EsportsGameResolveInput) -> EsportsGameResolutionResult:
        raise error

    register_game_resolution_tool(error_registry, fail)
    failed = asyncio.run(
        error_registry.execute(
            _call(
                {
                    "match_artifact_ref": "artifact:tool:" + "d" * 32,
                    "match_path": "items.0",
                    "game_position": 4,
                }
            )
        )
    )
    assert failed.status == "error"
    assert failed.error is not None and failed.error.code == "provider_timeout"


def test_renamed_pandascore_game_id_survives_artifact_continuation():
    from app.vnext.capabilities.esports.match import MatchSearchResult
    from app.vnext.providers.pandascore.match_adapter import PandaScoreMatchAdapter
    from tests.vnext.test_pandascore_match_adapter import _row

    source = _row()
    source["id"] = 1700719
    source["games"][0]["id"] = 739594
    item = PandaScoreMatchAdapter._normalize(source)
    document = MatchSearchResult(items=[item], page=1, limit=20).model_dump(mode="json")
    assert document["items"][0]["games"][0]["pandascore_game_id"] == 739594
    assert "id" not in document["items"][0]["games"][0]
    assert source["games"][0]["id"] == 739594
    calls = []

    class Service:
        async def resolve(self, match_id, game_position, *, confirmed_mappings):
            calls.append((match_id, game_position, confirmed_mappings))
            return _result().model_copy(update={"game_position": 1, "valve_game_id": 9018736585})

    async def run():
        store = SessionArtifactStore()
        ref = await store.put(document, source_tool="esports.match.search")
        continuation = GameResolutionContinuation(store, Service())
        return await continuation.resolve(
            EsportsGameResolveInput(
                match_artifact_ref=ref,
                match_path="items.0",
                game_position=1,
            )
        )

    result = asyncio.run(run())
    assert calls == [(1700719, 1, {})]
    assert result.valve_game_id == 9018736585


def test_missing_processor_fails_before_handler_and_save_failure_does_not_inline() -> None:
    called = False
    no_processor_registry = ToolRegistry()

    async def resolve(_request: EsportsGameResolveInput) -> EsportsGameResolutionResult:
        nonlocal called
        called = True
        return _result()

    register_game_resolution_tool(no_processor_registry, resolve)
    arguments = {
        "match_artifact_ref": "artifact:tool:" + "e" * 32,
        "match_path": "items.0",
        "game_position": 4,
    }
    missing_processor = asyncio.run(no_processor_registry.execute(_call(arguments)))
    assert missing_processor.status == "error"
    assert missing_processor.error is not None
    assert missing_processor.error.code == "artifact_error"
    assert called is False

    class _FailingStore(SessionArtifactStore):
        async def put(self, document: Any, source_tool: str | None = None) -> str:
            raise OSError("disk failure")

    failing_registry = ToolRegistry(result_processor=_processor(_FailingStore()))
    register_game_resolution_tool(failing_registry, resolve)
    failed = asyncio.run(failing_registry.execute(_call(arguments)))
    assert failed.status == "error"
    assert failed.error is not None and failed.error.code == "artifact_error"
    assert failed.content is None


def test_registry_preserves_argument_artifact_and_path_error_codes() -> None:
    store = SessionArtifactStore()

    class _UnusedService:
        async def resolve(self, *_args: Any, **_kwargs: Any) -> EsportsGameResolutionResult:
            raise AssertionError("selection failure must stop before Service call")

    continuation = GameResolutionContinuation(store, _UnusedService())  # type: ignore[arg-type]
    registry = ToolRegistry(result_processor=_processor(store))
    register_game_resolution_tool(registry, continuation.resolve)

    base = {
        "match_artifact_ref": "artifact:tool:" + "f" * 32,
        "match_path": "items.0",
        "game_position": 4,
    }
    malformed_ref = asyncio.run(
        registry.execute(_call({**base, "match_artifact_ref": "not-an-artifact"}))
    )
    assert malformed_ref.status == "error"
    assert malformed_ref.error is not None
    assert malformed_ref.error.code == "artifact_not_found"

    ref = asyncio.run(
        store.put(
            {"items": [], "page": 1, "limit": 20, "anomalies": []},
            source_tool="esports.match.search",
        )
    )
    missing_path = asyncio.run(registry.execute(_call({**base, "match_artifact_ref": ref})))
    assert missing_path.status == "error"
    assert missing_path.error is not None
    assert missing_path.error.code == "artifact_path_not_found"

    valid_doc = {
        "items": [
            {
                "id": 4,
                "name": "Match",
                "status": "finished",
                "draw": False,
                "forfeit": False,
                "rescheduled": False,
            }
        ],
        "page": 1,
        "limit": 20,
        "anomalies": [],
    }
    valid_ref = asyncio.run(store.put(valid_doc, source_tool="esports.match.search"))
    out_of_range = asyncio.run(
        registry.execute(_call({**base, "match_artifact_ref": valid_ref, "match_path": "items.1"}))
    )
    assert out_of_range.status == "error"
    assert out_of_range.error is not None
    assert out_of_range.error.code == "artifact_path_not_found"

    invalid_arguments = asyncio.run(registry.execute(_call({**base, "match_id": 123})))
    assert invalid_arguments.status == "error"
    assert invalid_arguments.error is not None
    assert invalid_arguments.error.code == "invalid_arguments"


def test_default_product_tool_inventory_does_not_register_resolution_yet() -> None:
    registry = build_vnext_registry(settings=VNextSettings())
    assert "esports.game.resolve" not in {tool.name for tool in registry.list()}
