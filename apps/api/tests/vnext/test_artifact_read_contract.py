"""Explicit artifact.read mode and error-mapping contracts."""

from __future__ import annotations

import asyncio

import pytest

from app.vnext.artifacts import (
    MAX_MODEL_TOOL_OBSERVATION_BYTES,
    ArtifactGrepper,
    ArtifactReader,
    SessionArtifactStore,
    serialized_size,
)
from app.vnext.llm.protocol import ToolCall
from app.vnext.tools.artifacts import register_artifact_tools
from app.vnext.tools.registry import ToolRegistry


async def _registry_with_document() -> tuple[ToolRegistry, str]:
    return await _registry_with_payload(
        {
            "resource": "tournament",
            "rows": [
                {"id": index, "games": [{"name": f"Game {index}"}]}
                for index in range(60)
            ],
        }
    )


async def _registry_with_payload(payload: dict[str, object]) -> tuple[ToolRegistry, str]:
    store = SessionArtifactStore()
    ref = await store.put(payload)
    registry = ToolRegistry()
    register_artifact_tools(registry, ArtifactReader(store), ArtifactGrepper(store))
    return registry, ref


def _call(arguments: dict[str, object]) -> ToolCall:
    return ToolCall(id="artifact-read", name="artifact.read", arguments=arguments)


def test_artifact_read_schema_explains_granularity_choices() -> None:
    store = SessionArtifactStore()
    registry = ToolRegistry()
    register_artifact_tools(registry, ArtifactReader(store), ArtifactGrepper(store))
    schema = registry.get("artifact.read").schema().input_schema
    properties = schema["properties"]

    assert "narrowest useful read granularity" in registry.get("artifact.read").description
    assert "parent collection such as rows" in properties["path"]["description"]
    assert "six complete adjacent rows" in properties["offset"]["description"]
    assert "one bounded parent-list read" in properties["limit"]["description"]
    assert "actual number returned may be lower" in properties["limit"]["description"]
    assert "fixed model observation-size budget" in registry.get("artifact.read").description
    assert "max_bytes" not in properties
    assert "max_tokens" not in properties
    assert "budget" not in properties


def test_outline_and_explicit_read_modes_are_unambiguous() -> None:
    async def exercise():
        registry, ref = await _registry_with_document()
        outline = await registry.execute(_call({"ref": ref, "mode": "outline"}))
        nested = await registry.execute(
            _call({"ref": ref, "mode": "read", "path": "rows.0.games"})
        )
        return outline, nested

    outline, nested = asyncio.run(exercise())

    assert outline.status == "ok"
    assert outline.content["path"] is None
    assert outline.content["value"] == {
        "resource": "tournament",
        "paths": [{"path": "rows", "kind": "collection", "count": 60}],
    }
    assert nested.status == "ok"
    assert nested.content["value"] == [{"name": "Game 0"}]
    assert nested.content["offset"] == 0
    assert nested.content["limit"] == 50


def test_read_list_uses_default_and_explicit_slices() -> None:
    async def exercise():
        registry, ref = await _registry_with_document()
        default = await registry.execute(_call({"ref": ref, "mode": "read", "path": "rows"}))
        explicit = await registry.execute(
            _call({"ref": ref, "mode": "read", "path": "rows", "offset": 10, "limit": 20})
        )
        return default, explicit

    default, explicit = asyncio.run(exercise())

    assert len(default.content["value"]) == 50
    assert default.content["offset"] == 0
    assert default.content["limit"] == 50
    assert [row["id"] for row in explicit.content["value"]] == list(range(10, 30))
    assert explicit.content["truncated"] is True


@pytest.mark.parametrize(
    "arguments",
    [
        {"mode": "outline", "path": "rows"},
        {"mode": "outline", "limit": 100},
        {"mode": "read"},
        {"limit": 100},
    ],
)
def test_schema_known_artifact_read_misuse_returns_invalid_arguments(
    arguments: dict[str, object],
) -> None:
    async def exercise():
        registry, ref = await _registry_with_document()
        return await registry.execute(_call({"ref": ref, **arguments}))

    result = asyncio.run(exercise())

    assert result.error is not None
    assert result.error.code == "invalid_arguments"


def test_runtime_read_validation_and_lookup_errors_are_specific() -> None:
    async def exercise():
        registry, ref = await _registry_with_document()
        scalar_limit = await registry.execute(
            _call({"ref": ref, "mode": "read", "path": "resource", "limit": 20})
        )
        invalid_path = await registry.execute(
            _call({"ref": ref, "mode": "read", "path": "rows.99"})
        )
        unknown = await registry.execute(
            _call(
                {
                    "ref": "artifact:tool:" + "0" * 32,
                    "mode": "outline",
                }
            )
        )
        return scalar_limit, invalid_path, unknown

    scalar_limit, invalid_path, unknown = asyncio.run(exercise())

    assert scalar_limit.error is not None
    assert scalar_limit.error.code == "invalid_arguments"
    assert invalid_path.error is not None
    assert invalid_path.error.code == "artifact_path_not_found"
    assert unknown.error is not None
    assert unknown.error.code == "artifact_not_found"


def test_byte_budget_truncates_complete_list_rows_and_supports_continuation() -> None:
    async def exercise():
        registry, ref = await _registry_with_payload(
            {
                "rows": [
                    {
                        "id": index,
                        "name": f"row-{index}",
                        "payload": "x" * 700,
                    }
                    for index in range(100)
                ]
            }
        )
        first = await registry.execute(
            _call({"ref": ref, "mode": "read", "path": "rows", "offset": 0, "limit": 40})
        )
        returned_count = len(first.content["value"])
        second = await registry.execute(
            _call(
                {
                    "ref": ref,
                    "mode": "read",
                    "path": "rows",
                    "offset": returned_count,
                    "limit": 40,
                }
            )
        )
        return first, second

    first, second = asyncio.run(exercise())

    assert first.status == "ok"
    assert 0 < len(first.content["value"]) < 40
    assert first.content["offset"] == 0
    assert first.content["limit"] == 40
    assert first.content["truncated"] is True
    assert serialized_size(first.content) <= MAX_MODEL_TOOL_OBSERVATION_BYTES
    assert all(set(row) == {"id", "name", "payload"} for row in first.content["value"])
    assert second.status == "ok"
    assert second.content["value"][0]["id"] == len(first.content["value"])


def test_byte_budget_uses_utf8_serialized_size() -> None:
    async def exercise():
        registry, ref = await _registry_with_payload(
            {
                "rows": [
                    {"id": index, "payload": "中文内容" * 350}
                    for index in range(30)
                ]
            }
        )
        return await registry.execute(
            _call({"ref": ref, "mode": "read", "path": "rows", "limit": 30})
        )

    result = asyncio.run(exercise())

    assert result.status == "ok"
    assert serialized_size(result.content) <= MAX_MODEL_TOOL_OBSERVATION_BYTES


def test_oversized_first_list_item_requires_narrower_path() -> None:
    async def exercise():
        registry, ref = await _registry_with_payload(
            {"rows": [{"id": 1, "payload": "x" * 9_000}]}
        )
        return await registry.execute(
            _call({"ref": ref, "mode": "read", "path": "rows", "limit": 1})
        )

    result = asyncio.run(exercise())

    assert result.status == "error"
    assert result.error is not None
    assert result.error.code == "invalid_arguments"
    assert "narrower nested path" in result.error.message


def test_oversized_non_list_values_are_rejected() -> None:
    async def exercise():
        registry, ref = await _registry_with_payload(
            {"large": {"payload": "x" * 9_000}, "large_text": "x" * 9_000}
        )
        large_object = await registry.execute(
            _call({"ref": ref, "mode": "read", "path": "large"})
        )
        large_scalar = await registry.execute(
            _call({"ref": ref, "mode": "read", "path": "large_text"})
        )
        return large_object, large_scalar

    large_object, large_scalar = asyncio.run(exercise())

    for result in (large_object, large_scalar):
        assert result.status == "error"
        assert result.error is not None
        assert result.error.code == "invalid_arguments"


def test_small_scalar_read_remains_unchanged() -> None:
    async def exercise():
        registry, ref = await _registry_with_document()
        return await registry.execute(_call({"ref": ref, "mode": "read", "path": "resource"}))

    result = asyncio.run(exercise())

    assert result.status == "ok"
    assert result.content == {
        "ref": result.content["ref"],
        "path": "resource",
        "value": "tournament",
        "offset": None,
        "limit": None,
        "total": None,
        "truncated": False,
    }


def test_oversized_outline_is_rejected_or_bounded() -> None:
    async def exercise():
        registry, ref = await _registry_with_payload(
            {f"key-{index}": "x" * 100 for index in range(200)}
        )
        return await registry.execute(_call({"ref": ref, "mode": "outline"}))

    result = asyncio.run(exercise())

    if result.status == "ok":
        assert serialized_size(result.content) <= MAX_MODEL_TOOL_OBSERVATION_BYTES
    else:
        assert result.error is not None
        assert result.error.code == "invalid_arguments"
