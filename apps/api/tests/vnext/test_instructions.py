from __future__ import annotations

from app.vnext.agent.instructions import AGENT_INSTRUCTION


def test_task_plan_policy_allows_checkpointable_result_units() -> None:
    instruction = " ".join(AGENT_INSTRUCTION.lower().split())

    assert "every item must be an artifact-backed" not in instruction
    assert "successful inline tool results" in instruction
    assert "can be checkpointed" in instruction
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


def test_historical_deferred_receipts_are_not_evidence_or_checkpoint_sources() -> None:
    instruction = " ".join(AGENT_INSTRUCTION.lower().split())

    assert "historical deferred receipts from older runs" in instruction
    assert "not evidence or checkpoint sources" in instruction
    assert (
        "does not release or replace the tool results retained in effective conversation history"
        in instruction
    )
    assert "successful inline tool results" in instruction
    assert "retry deferred materialization later" not in instruction
    assert "materialization budget" not in instruction
    assert "do not repeatedly retry a deferred materialization" not in instruction
    assert "160 kib" not in instruction
    assert "available bytes" not in instruction
