from __future__ import annotations

import asyncio

from app.vnext.artifacts import (
    MAX_MODEL_TOOL_OBSERVATION_BYTES,
    SessionArtifactStore,
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
