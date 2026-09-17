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


def test_task_plan_policy_allows_bounded_cross_partition_batching() -> None:
    instruction = " ".join(AGENT_INSTRUCTION.lower().split())

    assert "create the task plan before materializing substantial artifact content" in instruction
    assert "lightweight discovery may precede the plan" in instruction
    assert "do not require strictly serial retrieval" in instruction
    assert "batch or parallelize retrieval" in instruction
    assert "task_key" in instruction
    assert "checkpoint task items in plan order" in instruction
    assert "do not materialize large amounts of speculative evidence" in instruction
    assert "avoid materializing evidence for later task items" not in instruction
