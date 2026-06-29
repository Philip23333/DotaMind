from pydantic import BaseModel

from app.agentic.contracts import (
    CONTRACT_REGISTRY,
    STRUCTURED_OUTPUT_CONTRACTS,
    known_evidence_kinds,
    render_planner_contracts,
    validate_contract_plan_with_evidence,
    validate_plan_against_catalog,
)
from app.agentic.models import ExecutionPlan, ToolCall
from app.agentic.registry import ToolDefinition, ToolRegistry
from app.agentic.stratz_tools import build_default_tool_registry
from app.core.config import Settings

DEFAULT_EVIDENCE_KINDS = {
    "hero_identity",
    "matchup_win_rate",
    "sample_size",
    "patch_records",
    "hero_stats",
}


def _registry():
    return build_default_tool_registry(
        Settings(stratz_graphql_url="https://api.stratz.test/graphql", stratz_token="token")
    )


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


def test_contract_catalog_accepts_team_recent_report_evidence() -> None:
    plan = ExecutionPlan(
        intent="team_recent_performance",
        goal="Summarize recent team form.",
        output_contract="team_recent_report",
        tool_calls=[
            ToolCall(
                id="resolve_team",
                tool="opendota.resolve_team",
                args={"query": "Team BB"},
            ),
            ToolCall(
                id="get_matches",
                tool="opendota.team_recent_matches",
                args={"team_id": "$resolve_team.data.team.team_id", "days": 30},
            ),
            ToolCall(
                id="get_players",
                tool="opendota.team_players",
                args={"team_id": "$resolve_team.data.team.team_id", "current_only": True},
            ),
            ToolCall(
                id="get_heroes",
                tool="opendota.team_heroes",
                args={"matches": "$get_matches.data.matches"},
            ),
        ],
        required_evidence=[
            "team_identity",
            "recent_matches",
            "current_players",
            "team_hero_usage",
        ],
    )

    assert validate_plan_against_catalog(plan, _registry()) == []


def test_contract_catalog_rejects_natural_language_team_evidence_names() -> None:
    plan = ExecutionPlan(
        intent="team_recent_performance",
        goal="Summarize recent team form.",
        output_contract="team_recent_report",
        required_evidence=["team_identity", "matches", "roster", "hero_usage"],
    )

    errors = validate_plan_against_catalog(plan, _registry())

    assert "unknown required_evidence: hero_usage, matches, roster" in errors
    assert "team_recent_report plan missing required evidence: recent_matches" in errors


def test_contract_catalog_rejects_invalid_tool_args() -> None:
    plan = ExecutionPlan(
        intent="team_recent_performance",
        goal="Summarize recent team form.",
        output_contract="team_recent_report",
        tool_calls=[
            ToolCall(
                id="get_players",
                tool="opendota.team_players",
                args={"team_id": "$resolve_team.data.team.team_id", "current_roster": True},
            ),
            ToolCall(
                id="get_heroes",
                tool="opendota.team_heroes",
                args={"team_id": "$resolve_team.data.team.team_id"},
            ),
        ],
        required_evidence=["team_identity", "recent_matches"],
    )

    errors = validate_plan_against_catalog(plan, _registry())

    assert "opendota.team_players unknown args: current_roster" in errors
    assert "opendota.team_heroes unknown args: team_id" in errors


def test_contract_catalog_known_evidence_comes_from_registry() -> None:
    class DummyInput(BaseModel):
        query: str

    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="dummy.tool",
            description="Dummy tool.",
            input_model=DummyInput,
            handler=lambda args: {},
            evidence_kinds=("new_registry_evidence",),
        )
    )

    assert "new_registry_evidence" in known_evidence_kinds(registry)


def test_render_planner_contracts_contains_team_recent_example() -> None:
    rendered = render_planner_contracts(_registry())

    assert "team_recent_report" in rendered
    assert "recent_matches" in rendered
    assert "current_players" in rendered
    assert "team_hero_usage" in rendered
    assert '"matches": "$get_matches.data.matches"' in rendered


def test_render_planner_contracts_uses_null_for_unrestricted_allowed_evidence() -> None:
    rendered = render_planner_contracts(_registry())

    assert _contract_section(rendered, "patch_impact_report").endswith(
        'allowed_evidence: null\n  example: null'
    )
    assert _contract_section(rendered, "hero_matchup_report").endswith(
        'allowed_evidence: null\n  example: null'
    )
    assert _contract_section(rendered, "draft_advice").endswith(
        'allowed_evidence: null\n  example: null'
    )
    assert "allowed_evidence: []" not in rendered


def _contract_section(rendered: str, name: str) -> str:
    marker = f"- {name}"
    start = rendered.index(marker)
    next_start = rendered.find("\n- ", start + 1)
    if next_start == -1:
        return rendered[start:]
    return rendered[start:next_start]
