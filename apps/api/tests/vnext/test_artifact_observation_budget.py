from __future__ import annotations

import asyncio
from typing import Any

import pytest

from app.vnext.artifacts import (
    MAX_MODEL_TOOL_OBSERVATION_BYTES,
    ArtifactBackedToolResultProcessor,
    SessionArtifactStore,
    ToolResponseArtifactError,
    ToolResponseExternalizer,
    build_bounded_observation,
    serialized_size,
)


def _payload(text_length: int) -> dict[str, str]:
    return {"details": "x" * text_length}


def test_payload_between_old_and_new_observation_limits_is_complete() -> None:
    payload = _payload(20_000)

    assert 8 * 1024 < serialized_size(payload) < 35 * 1024

    observation = build_bounded_observation(payload, artifact_ref="artifact:tool:test")

    assert observation["value"]["details"] == payload["details"]
    assert serialized_size(observation) <= MAX_MODEL_TOOL_OBSERVATION_BYTES


def test_payload_above_new_observation_limit_remains_bounded() -> None:
    payload = _payload(40_000)

    observation = build_bounded_observation(payload, artifact_ref="artifact:tool:test")

    assert observation["value"]["details"] == {
        "_artifact_path": "details",
        "kind": "scalar",
    }
    assert serialized_size(observation) <= MAX_MODEL_TOOL_OBSERVATION_BYTES


def test_observation_budget_does_not_change_complete_artifact_storage() -> None:
    async def exercise() -> tuple[dict[str, str], dict[str, str]]:
        payload = _payload(20_000)
        store = SessionArtifactStore()
        decision = await ToolResponseExternalizer(store).externalize(payload)
        assert decision.artifact_ref is not None
        stored = await store.get(decision.artifact_ref)
        return payload, stored

    payload, stored = asyncio.run(exercise())

    assert stored == payload


def test_observation_builder_uses_each_callers_budget_independently() -> None:
    payload = {"details": "x" * 800}

    compact = build_bounded_observation(
        payload,
        artifact_ref="artifact:tool:test",
        max_bytes=150,
    )
    roomy = build_bounded_observation(
        payload,
        artifact_ref="artifact:tool:test",
        max_bytes=1_000,
    )

    assert serialized_size(compact) <= 150
    assert compact["value"]["details"]["_artifact_path"] == "details"
    assert serialized_size(roomy) <= 1_000
    assert roomy["value"]["details"] == payload["details"]


def test_observation_that_cannot_fit_its_base_envelope_fails() -> None:
    with pytest.raises(ToolResponseArtifactError, match="configured byte budget"):
        build_bounded_observation(
            {"details": "some value"},
            artifact_ref="artifact:tool:test",
            max_bytes=10,
        )


def test_processor_passes_configured_budget_to_injected_builder() -> None:
    async def exercise() -> tuple[dict[str, Any], int]:
        payload = {"result": "x" * 100}
        store = SessionArtifactStore()
        seen: dict[str, Any] = {}

        def builder(value: Any, *, artifact_ref: str, max_bytes: int) -> dict[str, Any]:
            seen["max_bytes"] = max_bytes
            return build_bounded_observation(
                value,
                artifact_ref=artifact_ref,
                max_bytes=max_bytes,
            )

        processor = ArtifactBackedToolResultProcessor(
            ToolResponseExternalizer(store, inline_max_bytes=1),
            observation_builder=builder,
            observation_max_bytes=256,
        )
        result = await processor.process(payload)
        return result.content, seen["max_bytes"]

    content, observed_budget = asyncio.run(exercise())

    assert observed_budget == 256
    assert serialized_size(content) <= 256
