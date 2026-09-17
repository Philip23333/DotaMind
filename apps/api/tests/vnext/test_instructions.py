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


def test_deferred_materialization_policy_guides_recovery_without_scheduler_details() -> None:
    instruction = " ".join(AGENT_INSTRUCTION.lower().split())

    assert "materializing tool may succeed" in instruction
    assert "deferred result means the tool execution succeeded" in instruction
    assert "not currently available in model context" in instruction
    assert "do not use a deferred result as evidence or as a checkpoint source" in instruction
    assert "checkpointing useful evidence" in instruction
    assert "retry deferred materialization later" in instruction
    assert "do not repeatedly retry a deferred materialization" in instruction
    assert "160 kib" not in instruction
    assert "available bytes" not in instruction
