from __future__ import annotations

import re

from app.vnext.agent.instructions import (
    AGENT_INSTRUCTION,
    ANSWER_INSTRUCTION,
    DEGRADED_ANSWER_INSTRUCTION,
    PRODUCT_INSTRUCTION,
)


def test_product_identity_is_shared_and_has_explicit_capability_boundaries() -> None:
    identity = " ".join(PRODUCT_INSTRUCTION.lower().split())

    assert "you are dotamind" in identity
    assert "dota 2 esports" in identity
    assert "players, teams, competitions, and match results" in identity
    assert "inference and data gaps" in identity
    assert "capabilities currently provided by this product" in identity
    assert "file processing" in identity
    assert "image processing" in identity
    assert "general web search" in identity
    assert "without calling tools" in identity
    assert "language used by the user" in identity
    assert re.search(r"\bfy\b|\bliquid\b|\bti 2024\b", identity) is None


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


def test_execution_evidence_rules_preserve_scope_entities_and_placement_uncertainty() -> None:
    instruction = " ".join(AGENT_INSTRUCTION.lower().split())

    assert "one retrieved page or slice" in instruction
    assert "does not prove that an upstream query exhausted its pages" in instruction
    assert "state any range that remains unverified" in instruction
    assert "verify that player's team membership" in instruction
    assert "current roster does not establish a historical roster" in instruction
    assert "do not infer a placement from a stage name alone" in instruction
    assert "say that placement is unverified" in instruction
    assert "checkpoint does not turn an inference into a verified fact" in instruction
    assert re.search(r"\bfy\b|\bliquid\b|\bti 2024\b", instruction) is None


def test_player_game_followups_preserve_exact_account_and_match_identity() -> None:
    instruction = " ".join(AGENT_INSTRUCTION.lower().split())

    assert "use `player.profile` when profile information is requested" in instruction
    assert "asks only for recent games, call `player.recent_games` directly" in instruction
    assert "request `game.detail` only for a selected or explicitly identified game" in instruction
    assert "pass its `valve_game_id` unchanged" in instruction
    assert "exact `account_id`" in instruction
    assert "never use the first player as a fallback" in instruction
    assert "do not fetch a new list to redefine its order" in instruction
    assert "if that list cannot be recovered" in instruction
    assert "labels from the reported valve catalog snapshot" in instruction
    assert "missing timeline or purchase data does not prove" in instruction
    assert re.search(r"\bfy\b|\bliquid\b|\bti 2024\b", instruction) is None


def test_answer_instructions_keep_requested_coverage_and_uncertainty() -> None:
    for prompt in (ANSWER_INSTRUCTION, DEGRADED_ANSWER_INSTRUCTION):
        normalized = " ".join(prompt.lower().split())
        assert "requested scope" in normalized
        assert "relevant results already obtained" in normalized
        assert "do not promote" in normalized or "do not promote an inference" in normalized
        assert "source-reported absence" in normalized
        assert "not yet been checked" in normalized or "ranges not yet checked" in normalized

    main = " ".join(ANSWER_INSTRUCTION.lower().split())
    assert "complete lists" in main
    assert "implying completeness by omitting" in main

    degraded = " ".join(DEGRADED_ANSWER_INSTRUCTION.lower().split())
    assert "keep each item's explanation brief" in degraded
    assert "do not silently drop key results" in degraded
