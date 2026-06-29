from app.agentic.contracts import (
    CONTRACT_REGISTRY,
    STRUCTURED_OUTPUT_CONTRACTS,
    validate_contract_plan_with_evidence,
)
from app.agentic.models import ExecutionPlan, ToolCall

DEFAULT_EVIDENCE_KINDS = {
    "hero_identity",
    "matchup_win_rate",
    "sample_size",
    "patch_records",
    "hero_stats",
}


def test_contract_registry_contains_allowed_output_contracts() -> None:
    assert {
        "patch_impact_report",
        "role_meta_report",
        "team_recent_report",
        "hero_matchup_report",
        "draft_advice",
        "natural_language_answer",
    } == set(CONTRACT_REGISTRY)


def test_meta_list_is_not_an_output_contract() -> None:
    assert "meta_list" not in CONTRACT_REGISTRY
    assert "natural_language_answer" not in STRUCTURED_OUTPUT_CONTRACTS


def test_patch_impact_contract_requires_records_tool_and_evidence() -> None:
    plan = ExecutionPlan(
        intent="patch_impact",
        goal="Patch summary.",
        output_contract="patch_impact_report",
        tool_calls=[],
        required_evidence=[],
    )

    errors = validate_contract_plan_with_evidence(plan, DEFAULT_EVIDENCE_KINDS)

    assert "patch_impact_report plan missing required evidence: patch_records" in errors
    assert "patch_impact_report plan must use patch.get_records" in errors


def test_role_meta_contract_rejects_field_names_as_evidence() -> None:
    plan = ExecutionPlan(
        intent="role_meta",
        goal="Role meta.",
        output_contract="role_meta_report",
        tool_calls=[
            ToolCall(
                id="stats",
                tool="opendota.hero_stats_by_role",
                args={"role": "offlane"},
            )
        ],
        required_evidence=["hero_stats", "hero_id", "win_rate"],
    )

    errors = validate_contract_plan_with_evidence(plan, DEFAULT_EVIDENCE_KINDS)

    assert "unknown required_evidence: hero_id, win_rate" in errors


def test_draft_advice_contract_requires_counter_pick_intent() -> None:
    plan = ExecutionPlan(
        intent="hero_matchup",
        goal="Draft answer.",
        output_contract="draft_advice",
        required_evidence=["hero_identity", "matchup_win_rate", "sample_size"],
    )

    errors = validate_contract_plan_with_evidence(plan, DEFAULT_EVIDENCE_KINDS)

    assert "draft_advice plan must use intent=counter_pick" in errors


def test_contract_validation_uses_supplied_evidence_kinds() -> None:
    plan = ExecutionPlan(
        intent="freeform",
        goal="Use newly registered evidence.",
        output_contract="natural_language_answer",
        required_evidence=["new_registry_evidence"],
    )

    errors = validate_contract_plan_with_evidence(plan, {"new_registry_evidence"})

    assert errors == []
