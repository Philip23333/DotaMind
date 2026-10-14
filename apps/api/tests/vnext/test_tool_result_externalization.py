from __future__ import annotations

import asyncio
from typing import Any

import pytest
from pydantic import BaseModel, ConfigDict

from app.vnext.artifacts import (
    MAX_MODEL_TOOL_OBSERVATION_BYTES,
    ArtifactBackedToolResultProcessor,
    ArtifactGrepper,
    ArtifactNotFoundError,
    ArtifactReader,
    SessionArtifactStore,
    ToolResponseExternalizer,
    serialized_size,
)
from app.vnext.capabilities.esports.dtos import MatchDTO
from app.vnext.capabilities.esports.match import MatchSearchResult
from app.vnext.llm.protocol import ToolCall
from app.vnext.tools.artifacts import register_artifact_tools
from app.vnext.tools.definition import ToolDefinition
from app.vnext.tools.registry import ToolRegistry


class EmptyInput(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PayloadOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[dict[str, Any]]
    page: int
    limit: int


def _registry(store: SessionArtifactStore) -> ToolRegistry:
    registry = ToolRegistry(
        result_processor=ArtifactBackedToolResultProcessor(
            ToolResponseExternalizer(store)
        )
    )
    register_artifact_tools(
        registry,
        ArtifactReader(store),
        ArtifactGrepper(store),
    )
    return registry


def _register_payload_tool(registry: ToolRegistry, payload: dict[str, Any]) -> None:
    registry.register(
        ToolDefinition(
            name="test.payload",
            description="Return a payload for externalization testing.",
            input_model=EmptyInput,
            output_model=PayloadOutput,
            handler=lambda _args: payload,
        )
    )


def _call() -> ToolCall:
    return ToolCall(id="payload-call", name="test.payload", arguments={})


def test_small_tool_output_remains_inline() -> None:
    store = SessionArtifactStore()
    registry = _registry(store)
    payload = {"items": [{"id": 1}], "page": 1, "limit": 1}
    _register_payload_tool(registry, payload)

    result = asyncio.run(registry.execute(_call()))

    assert result.status == "ok"
    assert result.content == payload
    assert store._documents == {}


def test_configured_inline_threshold_includes_equal_size_only() -> None:
    async def exercise():
        store = SessionArtifactStore()
        payload = {"value": "x"}
        threshold = serialized_size(payload)
        externalizer = ToolResponseExternalizer(store, inline_max_bytes=threshold)
        equal = await externalizer.externalize(payload)
        over = await externalizer.externalize({"value": "xx"})
        return store, threshold, equal, over

    store, threshold, equal, over = asyncio.run(exercise())

    assert threshold == serialized_size({"value": "x"})
    assert equal.artifact_ref is None
    assert over.artifact_ref is not None
    assert asyncio.run(store.get(over.artifact_ref)) == {"value": "xx"}


def test_large_tool_output_is_externalized_with_bounded_observation() -> None:
    store = SessionArtifactStore()
    registry = _registry(store)
    payload = {
        "items": [
            {"id": index, "payload": "x" * 1000}
            for index in range(100)
        ],
        "page": 1,
        "limit": 100,
    }
    assert serialized_size(payload) > 12 * 1024
    _register_payload_tool(registry, payload)

    result = asyncio.run(registry.execute(_call()))

    assert result.status == "ok"
    assert result.content["externalized"] is True
    ref = result.content["artifact_ref"]
    assert ref.startswith("artifact:tool:")
    assert result.content["value"]["items"] == {
        "_artifact_path": "items",
        "kind": "collection",
        "count": 100,
    }
    assert serialized_size(result.content) <= MAX_MODEL_TOOL_OBSERVATION_BYTES

    stored = asyncio.run(store.get(ref))
    assert stored == payload
    assert asyncio.run(store.get_source_tool(ref)) == "test.payload"


def test_externalized_full_output_is_retrievable_through_artifact_tool() -> None:
    store = SessionArtifactStore()
    registry = _registry(store)
    payload = {
        "items": [
            {"id": index, "payload": "x" * 1000}
            for index in range(100)
        ],
        "page": 1,
        "limit": 100,
    }
    _register_payload_tool(registry, payload)

    result = asyncio.run(registry.execute(_call()))
    ref = result.content["artifact_ref"]
    read = asyncio.run(
        registry.execute(
            ToolCall(
                id="read-call",
                name="artifact.read",
                arguments={
                    "ref": ref,
                    "mode": "read",
                    "path": "items",
                    "offset": 0,
                    "limit": 10,
                },
            )
        )
    )

    assert read.status == "ok"
    returned_items = read.content["value"]
    assert 0 < len(returned_items) <= 10
    assert returned_items == payload["items"][: len(returned_items)]
    assert read.content["total"] == 100
    assert read.content["truncated"] is True
    assert serialized_size(read.content) <= MAX_MODEL_TOOL_OBSERVATION_BYTES

    continuation = asyncio.run(
        registry.execute(
            ToolCall(
                id="read-continuation-call",
                name="artifact.read",
                arguments={
                    "ref": ref,
                    "mode": "read",
                    "path": "items",
                    "offset": len(returned_items),
                    "limit": 10,
                },
            )
        )
    )
    assert continuation.status == "ok"
    assert continuation.content["value"][0] == payload["items"][len(returned_items)]


def test_artifact_tools_bypass_result_externalization() -> None:
    store = SessionArtifactStore()
    registry = _registry(store)

    assert registry.get("artifact.read").externalize_result is False
    assert registry.get("artifact.grep").externalize_result is False


def test_anonymous_artifact_remains_readable_and_searchable_without_source() -> None:
    store = SessionArtifactStore()
    ref = asyncio.run(store.put({"items": [{"name": "Team Spirit"}]}))
    registry = _registry(store)

    read = asyncio.run(
        registry.execute(
            ToolCall(
                id="anonymous-read",
                name="artifact.read",
                arguments={"ref": ref, "mode": "read", "path": "items"},
            )
        )
    )
    grep = asyncio.run(
        registry.execute(
            ToolCall(
                id="anonymous-grep",
                name="artifact.grep",
                arguments={"ref": ref, "pattern": "spirit"},
            )
        )
    )

    assert read.status == "ok"
    assert read.content["value"] == [{"name": "Team Spirit"}]
    assert grep.status == "ok"
    assert grep.content["matches"]
    assert asyncio.run(store.get_source_tool(ref)) is None
    assert len(store._documents) == 1


def test_artifact_body_and_source_are_session_local() -> None:
    first = SessionArtifactStore()
    second = SessionArtifactStore()
    ref = asyncio.run(first.put({"items": []}, source_tool="esports.match.search"))

    with pytest.raises(ArtifactNotFoundError):
        asyncio.run(second.get(ref))
    with pytest.raises(ArtifactNotFoundError):
        asyncio.run(second.get_source_tool(ref))

    assert asyncio.run(first.get_source_tool(ref)) == "esports.match.search"


def test_artifact_source_is_store_metadata_not_document_content() -> None:
    store = SessionArtifactStore()
    registry = _registry(store)
    payload = {
        "items": [{"source_tool": "forged-tool", "payload": "x" * 13_000}],
        "page": 1,
        "limit": 1,
    }
    _register_payload_tool(registry, payload)

    result = asyncio.run(registry.execute(_call()))
    assert result.status == "ok"
    ref = result.content["artifact_ref"]
    assert asyncio.run(store.get(ref)) == payload
    assert asyncio.run(store.get_source_tool(ref)) == "test.payload"


def test_always_artifact_stores_small_match_with_complete_value_and_source() -> None:
    store = SessionArtifactStore()
    registry = _registry(store)
    payload = {"items": [{"id": 42, "name": "Final"}], "page": 1, "limit": 20}
    registry.register(
        ToolDefinition(
            name="esports.match.search",
            description="Search matches.",
            input_model=EmptyInput,
            output_model=PayloadOutput,
            handler=lambda _args: payload,
            always_artifact=True,
        )
    )

    result = asyncio.run(registry.execute(_call_match()))

    assert result.status == "ok"
    ref = result.content["artifact_ref"]
    assert result.content == {
        "artifact_ref": ref,
        "externalized": True,
        "value": payload,
    }
    assert asyncio.run(store.get(ref)) == payload
    assert asyncio.run(store.get_source_tool(ref)) == "esports.match.search"
    assert len(store._documents) == 1


def test_forced_small_result_falls_back_to_bounded_observation_when_envelope_is_too_large() -> None:
    async def exercise():
        store = SessionArtifactStore()
        processor = ArtifactBackedToolResultProcessor(
            ToolResponseExternalizer(store, inline_max_bytes=1000),
            observation_max_bytes=140,
        )
        payload = {"items": [{"id": 42, "name": "A very long display name"}], "page": 1}
        result = await processor.process(
            payload,
            source_tool="esports.match.search",
            force_artifact=True,
        )
        return store, payload, result

    store, payload, result = asyncio.run(exercise())
    assert result.artifact_ref is not None
    assert result.content["externalized"] is True
    assert result.content["value"] != payload
    assert serialized_size(result.content) <= 140
    assert asyncio.run(store.get(result.artifact_ref)) == payload


def test_always_artifact_requires_strict_flag_and_externalization() -> None:
    with pytest.raises(TypeError, match="always_artifact must be a bool"):
        ToolDefinition(
            name="test.invalid",
            description="Invalid flag.",
            input_model=EmptyInput,
            output_model=PayloadOutput,
            handler=lambda _args: {},
            always_artifact=1,  # type: ignore[arg-type]
        )
    with pytest.raises(ValueError, match="requires externalize_result=True"):
        ToolDefinition(
            name="test.invalid",
            description="Invalid flag combination.",
            input_model=EmptyInput,
            output_model=PayloadOutput,
            handler=lambda _args: {},
            externalize_result=False,
            always_artifact=True,
        )


def test_always_artifact_without_processor_fails_before_handler() -> None:
    called = False

    def handler(_args):
        nonlocal called
        called = True
        return {"items": [], "page": 1, "limit": 1}

    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="test.required-artifact",
            description="Requires an Artifact processor.",
            input_model=EmptyInput,
            output_model=PayloadOutput,
            handler=handler,
            always_artifact=True,
        )
    )
    result = asyncio.run(
        registry.execute(
            ToolCall(id="no-processor", name="test.required-artifact", arguments={})
        )
    )

    assert result.status == "error"
    assert result.error is not None and result.error.code == "artifact_error"
    assert called is False


def test_artifact_save_failure_does_not_fall_back_to_inline_success() -> None:
    class FailingStore(SessionArtifactStore):
        async def put(self, document: Any, source_tool: str | None = None) -> str:
            raise OSError("simulated storage failure")

    store = FailingStore()
    processor = ArtifactBackedToolResultProcessor(ToolResponseExternalizer(store))
    registry = ToolRegistry(result_processor=processor)
    payload = {"items": [], "page": 1, "limit": 1}
    registry.register(
        ToolDefinition(
            name="test.forced",
            description="Require storage before returning success.",
            input_model=EmptyInput,
            output_model=PayloadOutput,
            handler=lambda _args: payload,
            always_artifact=True,
        )
    )

    result = asyncio.run(
        registry.execute(
            ToolCall(id="failed-artifact", name="test.forced", arguments={})
        )
    )

    assert result.status == "error"
    assert result.error is not None and result.error.code == "artifact_error"
    assert result.content is None
    assert store._documents == {}


def test_match_search_result_is_externalized_without_field_selection() -> None:
    store = SessionArtifactStore()
    registry = _registry(store)
    items = [
        MatchDTO(
            id=index,
            name=f"Match {index}",
            status="finished",
            draw=False,
            forfeit=False,
            rescheduled=False,
        )
        for index in range(100)
    ]
    expected = MatchSearchResult(items=items, page=1, limit=100).model_dump(mode="json")
    registry.register(
        ToolDefinition(
            name="esports.match.search",
            description="Return a match-search result for externalization testing.",
            input_model=EmptyInput,
            output_model=MatchSearchResult,
            handler=lambda _args: expected,
            always_artifact=True,
        )
    )

    result = asyncio.run(
        registry.execute(
            ToolCall(id="match-call", name="esports.match.search", arguments={})
        )
    )

    assert result.status == "ok"
    assert result.content["externalized"] is True
    assert result.content["value"]["items"] == {
        "_artifact_path": "items",
        "kind": "collection",
        "count": 100,
    }
    ref = result.content["artifact_ref"]
    assert asyncio.run(store.get(ref)) == expected
    assert asyncio.run(store.get_source_tool(ref)) == "esports.match.search"
    assert len(store._documents) == 1
    assert serialized_size(result.content) <= MAX_MODEL_TOOL_OBSERVATION_BYTES


def _call_match() -> ToolCall:
    return ToolCall(id="match-call", name="esports.match.search", arguments={})
