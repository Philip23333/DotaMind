from __future__ import annotations

import json
from pathlib import Path


_CASES = Path(__file__).parent / "evals" / "task_plan_generalization_cases.json"


def _cases() -> list[dict[str, object]]:
    return json.loads(_CASES.read_text(encoding="utf-8"))


def test_task_plan_generalization_catalog_covers_distinct_partition_axes() -> None:
    cases = _cases()

    assert len(cases) >= 6
    categories = {case["category"] for case in cases}

    assert {
        "temporal",
        "entity",
        "player",
        "competition",
        "hybrid",
        "single_deep",
    } <= categories


def test_task_plan_generalization_catalog_does_not_encode_fixed_plans() -> None:
    cases = _cases()

    for case in cases:
        assert "expected_keys" not in case
        assert "required_keys" not in case
        assert "expected_item_count" not in case
        assert "required_tool_sequence" not in case
        assert case["acceptable_partition_axes"]


def test_task_plan_generalization_case_ids_are_unique() -> None:
    cases = _cases()
    ids = [case["id"] for case in cases]

    assert len(ids) == len(set(ids))
