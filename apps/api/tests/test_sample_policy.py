from typing import Any

import pytest
import yaml

from app.agentic.models import ExecutionPlan, ToolCall
from app.agentic.planning.sample_policy import (
    apply_sample_policy,
    render_sample_policy,
)
from app.agentic.tools.stratz_tools import build_default_tool_registry
from app.core.config import DEFAULT_POLICY_PATH, AppPolicy, Settings, get_policy, load_policy


def _registry():
    return build_default_tool_registry(
        Settings(stratz_graphql_url="https://api.stratz.test/graphql", stratz_token="token")
    )


def _policy() -> AppPolicy:
    return get_policy()


def _policy_with_tools(tools: dict[str, dict[str, Any]]) -> AppPolicy:
    """Build a full AppPolicy from the real yaml, overriding the sample_policy
    tools block. Keeps validators (e.g. relaxed<=default<=strict) in play."""
    data = yaml.safe_load(DEFAULT_POLICY_PATH.read_text(encoding="utf-8"))
    data["planning"]["sample_policy"]["tools"] = tools
    return AppPolicy.model_validate(data)


def _plan(tool: str, args: dict[str, Any]) -> ExecutionPlan:
    return ExecutionPlan(
        intent="t",
        goal="t",
        output_contract="natural_language_answer",
        tool_calls=[ToolCall(id="c1", tool=tool, args=dict(args))],
    )


# --- apply_sample_policy -----------------------------------------------------


def test_apply_fills_default_for_missing_arg_and_records_provenance() -> None:
    plan = _plan("stratz.hero_matchup_ranking", {"hero_id": 25, "side": "vs", "take": 5})
    apply_sample_policy(plan, _policy())

    assert plan.tool_calls[0].args["min_sample_size"] == 2000
    applied = plan.metadata["policy_applied"]
    assert len(applied) == 1
    record = applied[0]
    assert record == {
        "tool_call_id": "c1",
        "tool": "stratz.hero_matchup_ranking",
        "arg": "min_sample_size",
        "mode": "default",
        "value": 2000,
        "reason": "sample_policy default (planner did not set it)",
    }


def test_apply_preserves_explicit_value_and_records_no_provenance() -> None:
    # LLM chose relaxed (500) explicitly — preserved, not tagged in provenance.
    plan = _plan(
        "stratz.hero_matchup_ranking",
        {"hero_id": 25, "side": "vs", "take": 5, "min_sample_size": 500},
    )
    apply_sample_policy(plan, _policy())

    assert plan.tool_calls[0].args["min_sample_size"] == 500
    # No policy_applied key at all when nothing was injected.
    assert plan.metadata.get("policy_applied") is None


def test_apply_treats_zero_as_explicit_not_missing() -> None:
    # 0 is a legitimate explicit floor (popular/full-distribution); not a
    # sentinel for "omitted". Must be preserved without provenance.
    plan = _plan(
        "stratz.hero_matchup_ranking",
        {"hero_id": 25, "side": "vs", "take": 5, "min_sample_size": 0},
    )
    apply_sample_policy(plan, _policy())

    assert plan.tool_calls[0].args["min_sample_size"] == 0
    assert plan.metadata.get("policy_applied") is None


def test_apply_treats_explicit_null_as_missing_and_backfills_default() -> None:
    # Defends against the LLM emitting JSON null: without backfill, validate
    # would reject None as not-an-int. Backfill converts it to the default.
    plan = _plan(
        "stratz.hero_matchup_ranking",
        {"hero_id": 25, "side": "vs", "take": 5, "min_sample_size": None},
    )
    apply_sample_policy(plan, _policy())

    assert plan.tool_calls[0].args["min_sample_size"] == 2000
    applied = plan.metadata["policy_applied"]
    assert len(applied) == 1
    assert applied[0]["tool_call_id"] == "c1"


def test_apply_skips_tool_not_enrolled_in_policy() -> None:
    plan = _plan("resolve_hero", {"query": "Lina"})
    apply_sample_policy(plan, _policy())

    assert "min_sample_size" not in plan.tool_calls[0].args
    assert plan.metadata.get("policy_applied") is None


def test_apply_handles_filter_tool_uses_min_position_match_count_arg() -> None:
    # Generic over `arg`: filter_heroes_by_position uses min_position_match_count.
    plan = _plan(
        "stratz.filter_heroes_by_position",
        {"candidate_rows": [{"hero_id": 1}], "position_id": "POSITION_4"},
    )
    apply_sample_policy(plan, _policy())

    assert plan.tool_calls[0].args["min_position_match_count"] == 1000
    record = plan.metadata["policy_applied"][0]
    assert record["arg"] == "min_position_match_count"
    assert record["value"] == 1000


def test_apply_mixed_calls_only_backfills_missing() -> None:
    plan = ExecutionPlan(
        intent="t",
        goal="t",
        output_contract="natural_language_answer",
        tool_calls=[
            ToolCall(
                id="omit",
                tool="stratz.hero_matchup_ranking",
                args={"hero_id": 25, "side": "vs", "take": 5},
            ),
            ToolCall(
                id="explicit",
                tool="stratz.hero_matchup_ranking",
                args={"hero_id": 26, "side": "vs", "take": 5, "min_sample_size": 5000},
            ),
            ToolCall(
                id="null",
                tool="stratz.hero_matchup_ranking",
                args={"hero_id": 27, "side": "vs", "take": 5, "min_sample_size": None},
            ),
            ToolCall(id="resolve", tool="resolve_hero", args={"query": "Lina"}),
        ],
    )
    apply_sample_policy(plan, _policy())

    values = [c.args.get("min_sample_size") for c in plan.tool_calls]
    assert values == [2000, 5000, 2000, None]
    applied_ids = [r["tool_call_id"] for r in plan.metadata["policy_applied"]]
    assert applied_ids == ["omit", "null"]


def test_apply_no_op_when_policy_has_no_tools() -> None:
    policy = _policy_with_tools(tools={})
    plan = _plan(
        "stratz.hero_matchup_ranking",
        {"hero_id": 25, "side": "vs", "take": 5},
    )
    apply_sample_policy(plan, policy)

    assert "min_sample_size" not in plan.tool_calls[0].args
    assert plan.metadata.get("policy_applied") is None


# --- render_sample_policy ----------------------------------------------------


def test_render_contains_per_tool_table_and_four_modes() -> None:
    rendered = render_sample_policy(_policy(), _registry())

    # 4 modes named + priority order.
    assert "Sample-size policy" in rendered
    assert "explicit" in rendered
    assert "strict" in rendered
    assert "relaxed" in rendered
    assert "default" in rendered
    assert "explicit > strict > relaxed > default" in rendered
    # Per-tool table covers all 5 enrolled tools.
    assert (
        "- stratz.hero_matchup_ranking.min_sample_size: "
        "default=2000 relaxed=500 strict=5000"
    ) in rendered
    assert (
        "- stratz.hero_synergy_ranking.min_sample_size: "
        "default=2000 relaxed=500 strict=5000"
    ) in rendered
    assert (
        "- stratz.lane_meta_global.min_sample_size: "
        "default=1000 relaxed=300 strict=3000"
    ) in rendered
    assert (
        "- stratz.hero_position_stats.min_sample_size: "
        "default=1000 relaxed=300 strict=3000"
    ) in rendered
    assert (
        "- stratz.filter_heroes_by_position.min_position_match_count: "
        "default=1000 relaxed=300 strict=3000"
    ) in rendered


def test_render_rejects_unknown_tool_typo() -> None:
    data = yaml.safe_load(DEFAULT_POLICY_PATH.read_text(encoding="utf-8"))
    tools = data["planning"]["sample_policy"]["tools"]
    tools["stratz.hero_matchup_RANKING_typo"] = dict(tools["stratz.hero_matchup_ranking"])
    policy = AppPolicy.model_validate(data)

    with pytest.raises(ValueError, match="unknown tool"):
        render_sample_policy(policy, _registry())


def test_render_rejects_unknown_arg_typo() -> None:
    data = yaml.safe_load(DEFAULT_POLICY_PATH.read_text(encoding="utf-8"))
    data["planning"]["sample_policy"]["tools"]["stratz.hero_matchup_ranking"]["arg"] = (
        "min_sample_SIZE_typo"
    )
    policy = AppPolicy.model_validate(data)

    with pytest.raises(ValueError, match="not a field"):
        render_sample_policy(policy, _registry())


def test_render_without_any_tools_still_emits_modes() -> None:
    policy = _policy_with_tools(tools={})
    rendered = render_sample_policy(policy, _registry())

    assert "Sample-size policy" in rendered
    assert "explicit > strict > relaxed > default" in rendered
    # No per-tool table lines.
    assert "stratz.hero_matchup_ranking.min_sample_size" not in rendered


# --- tool-default / policy consistency --------------------------------------


def test_stratz_tool_defaults_match_sample_policy() -> None:
    """Guard against double-write drift: each enrolled tool's input_model Field
    default must equal the policy default. Covers all 5 (and any future adds)."""
    registry = _registry()
    policy = _policy()
    for tool_name, entry in policy.planning.sample_policy.tools.items():
        definition = registry.get(tool_name)
        field_default = definition.input_model.model_fields[entry.arg].default
        assert field_default == entry.default, (
            f"{tool_name}.{entry.arg} Field default ({field_default}) "
            f"!= policy default ({entry.default}); update the Field or policy.yaml"
        )


def test_policy_yaml_sample_policy_loads_expected_defaults() -> None:
    policy = load_policy(DEFAULT_POLICY_PATH)
    tools = policy.planning.sample_policy.tools
    assert set(tools) == {
        "stratz.hero_matchup_ranking",
        "stratz.hero_synergy_ranking",
        "stratz.lane_meta_global",
        "stratz.hero_position_stats",
        "stratz.filter_heroes_by_position",
    }
    assert tools["stratz.hero_matchup_ranking"].default == 2000
    assert tools["stratz.hero_matchup_ranking"].relaxed == 500
    assert tools["stratz.hero_matchup_ranking"].strict == 5000
    assert tools["stratz.filter_heroes_by_position"].arg == "min_position_match_count"
    assert tools["stratz.lane_meta_global"].default == 1000
