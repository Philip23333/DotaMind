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


def test_task_plan_policy_scopes_materialization_to_known_current_partitions() -> None:
    instruction = " ".join(AGENT_INSTRUCTION.lower().split())

    assert "create the task plan before materializing substantial artifact content" in instruction
    assert "lightweight discovery may precede the plan" in instruction
    assert "avoid materializing evidence for later task items" in instruction
    assert "parallel tool use within the current item is allowed" in instruction
