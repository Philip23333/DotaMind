"""Explicit artifact.read mode and error-mapping contracts."""

from __future__ import annotations

import asyncio

import pytest

from app.vnext.artifacts import ArtifactGrepper, ArtifactReader, SessionArtifactStore
from app.vnext.llm.protocol import ToolCall
from app.vnext.tools.artifacts import register_artifact_tools
from app.vnext.tools.registry import ToolRegistry


async def _registry_with_document() -> tuple[ToolRegistry, str]:
    store = SessionArtifactStore()
    ref = await store.put(
        {
            "resource": "tournament",
            "rows": [
                {"id": index, "games": [{"name": f"Game {index}"}]}
                for index in range(60)
            ],
        }
    )
    registry = ToolRegistry()
    register_artifact_tools(registry, ArtifactReader(store), ArtifactGrepper(store))
    return registry, ref


def _call(arguments: dict[str, object]) -> ToolCall:
    return ToolCall(id="artifact-read", name="artifact.read", arguments=arguments)


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
        "sections": {"rows": {"kind": "collection", "count": 60}},
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
