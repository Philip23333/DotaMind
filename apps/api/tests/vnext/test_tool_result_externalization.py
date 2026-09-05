from __future__ import annotations

import asyncio
from typing import Any

from pydantic import BaseModel, ConfigDict

from app.vnext.artifacts import (
    MAX_MODEL_TOOL_OBSERVATION_BYTES,
    ArtifactBackedToolResultProcessor,
    ArtifactGrepper,
    ArtifactReader,
    SessionArtifactStore,
    ToolResponseExternalizer,
    serialized_size,
)
from app.vnext.capabilities.esports.match import MatchItem, MatchSearchResult
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
    assert read.content["value"] == payload["items"][:10]
    assert read.content["total"] == 100
    assert read.content["truncated"] is True


def test_artifact_tools_bypass_result_externalization() -> None:
    store = SessionArtifactStore()
    registry = _registry(store)

    assert registry.get("artifact.read").externalize_result is False
    assert registry.get("artifact.grep").externalize_result is False


def test_match_search_result_is_externalized_without_field_selection() -> None:
    store = SessionArtifactStore()
    registry = _registry(store)
    items = [MatchItem(id=index) for index in range(100)]
    expected = MatchSearchResult(items=items, page=1, limit=100).model_dump(mode="json")
    registry.register(
        ToolDefinition(
            name="esports.match.search",
            description="Return a match-search result for externalization testing.",
            input_model=EmptyInput,
            output_model=MatchSearchResult,
            handler=lambda _args: expected,
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
