from __future__ import annotations

from app.vnext.agent.instructions import AGENT_INSTRUCTION


def test_task_plan_policy_is_limited_to_checkpointable_retrieval_units() -> None:
    instruction = AGENT_INSTRUCTION.lower()

    assert "artifact-backed retrieval unit" in instruction
    assert "checkpointable" in instruction
    assert "final synthesis" in instruction
    assert "comparison" in instruction
    assert "aggregation" in instruction
    assert "answer composition" in instruction
    assert "checkpointed taskstate" in instruction
