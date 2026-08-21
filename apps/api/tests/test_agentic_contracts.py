from pydantic import BaseModel

from app.agentic.models import ExecutionPlan, ToolCall
from app.agentic.planning.contracts import (
    CONTRACT_REGISTRY,
    STRUCTURED_OUTPUT_CONTRACTS,
    known_evidence_kinds,
    render_controller_contracts,
    render_controller_tools,
    validate_contract_plan_with_evidence,
    validate_plan_against_catalog,
    validate_registry_contracts,
)
from app.agentic.tools import (
    AcceptedRef,
    ArgContract,
    OutputPathContract,
    ToolDefinition,
    ToolRegistry,
)
from app.agentic.tools.stratz_tools import build_default_tool_registry
from app.core.config import Settings

DEFAULT_EVIDENCE_KINDS = {
    "hero_identity",
    "pair_lane_outcome",
    "matchup_ranking_row",
    "lane_meta_row",
    "position_stat",
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


def test_contract_catalog_accepts_any_previous_declared_reference_call_id() -> None:
    plan = ExecutionPlan(
        intent="pair_lane_outcome",
        goal="Show SK + AA pair lane outcome.",
        output_contract="natural_language_answer",
        tool_calls=[
            ToolCall(
                id="resolve_sk",
                tool="resolve_hero",
                args={"query": "骷髅王"},
            ),
            ToolCall(
                id="resolve_aa",
                tool="resolve_hero",
                args={"query": "冰魂"},
            ),
            ToolCall(
                id="pair_lane",
                tool="stratz.pair_lane_outcome",
                args={
                    "hero_id": "$resolve_sk.data.hero.hero_id",
                    "partner_hero_id": "$resolve_aa.data.hero.hero_id",
                    "is_with": True,
                },
            ),
        ],
        required_evidence=["hero_identity", "pair_lane_outcome", "sample_size"],
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


def test_contract_catalog_rejects_missing_required_tool_arg() -> None:
    plan = ExecutionPlan(
        intent="pair_lane_outcome",
        goal="Show pair lane outcome.",
        output_contract="natural_language_answer",
        tool_calls=[
            ToolCall(
                id="resolve_sk",
                tool="resolve_hero",
                args={"query": "骷髅王"},
            ),
            ToolCall(
                id="pair_lane",
                tool="stratz.pair_lane_outcome",
                args={
                    "hero_id": "$resolve_sk.data.hero.hero_id",
                    "is_with": True,
                },
            ),
        ],
        required_evidence=["hero_identity", "pair_lane_outcome", "sample_size"],
    )

    errors = validate_plan_against_catalog(plan, _registry())

    assert any("stratz.pair_lane_outcome invalid args" in item for item in errors)


def test_contract_catalog_rejects_future_reference() -> None:
    plan = ExecutionPlan(
        intent="pair_lane_outcome",
        goal="Show pair lane outcome.",
        output_contract="natural_language_answer",
        tool_calls=[
            ToolCall(
                id="pair_lane",
                tool="stratz.pair_lane_outcome",
                args={
                    "hero_id": "$resolve_sk.data.hero.hero_id",
                    "partner_hero_id": "$resolve_aa.data.hero.hero_id",
                    "is_with": True,
                },
            ),
            ToolCall(
                id="resolve_sk",
                tool="resolve_hero",
                args={"query": "骷髅王"},
            ),
            ToolCall(
                id="resolve_aa",
                tool="resolve_hero",
                args={"query": "冰魂"},
            ),
        ],
        required_evidence=["hero_identity", "pair_lane_outcome", "sample_size"],
    )

    errors = validate_plan_against_catalog(plan, _registry())

    assert any("reference target must be a previous tool call" in item for item in errors)


def test_contract_catalog_rejects_undeclared_reference_path() -> None:
    plan = ExecutionPlan(
        intent="pair_lane_outcome",
        goal="Show pair lane outcome.",
        output_contract="natural_language_answer",
        tool_calls=[
            ToolCall(id="resolve_sk", tool="resolve_hero", args={"query": "骷髅王"}),
            ToolCall(id="resolve_aa", tool="resolve_hero", args={"query": "冰魂"}),
            ToolCall(
                id="pair_lane",
                tool="stratz.pair_lane_outcome",
                args={
                    "hero_id": "$resolve_sk.data.hero.missing",
                    "partner_hero_id": "$resolve_aa.data.hero.hero_id",
                    "is_with": True,
                },
            ),
        ],
        required_evidence=["hero_identity", "pair_lane_outcome", "sample_size"],
    )

    errors = validate_plan_against_catalog(plan, _registry())

    assert any("reference path is not declared" in item for item in errors)


def test_contract_catalog_rejects_unproducible_required_evidence() -> None:
    plan = ExecutionPlan(
        intent="pair_lane_outcome",
        goal="Show pair lane outcome.",
        output_contract="natural_language_answer",
        tool_calls=[
            ToolCall(id="resolve_sk", tool="resolve_hero", args={"query": "骷髅王"}),
        ],
        required_evidence=["hero_identity", "pair_lane_outcome"],
    )

    errors = validate_plan_against_catalog(plan, _registry())

    assert any("not producible by selected tools: pair_lane_outcome" in item for item in errors)


def test_contract_runtime_accepts_dummy_declared_reference() -> None:
    registry = _dummy_registry()
    plan = ExecutionPlan(
        intent="dummy",
        goal="Use generic references.",
        output_contract="natural_language_answer",
        tool_calls=[
            ToolCall(id="source_call", tool="dummy.source", args={}),
            ToolCall(
                id="consumer_call",
                tool="dummy.consumer",
                args={"value": "$source_call.data.value"},
            ),
        ],
        required_evidence=["dummy_value"],
    )

    assert validate_plan_against_catalog(plan, registry) == []


def test_registry_startup_rejects_dummy_type_mismatch_reference() -> None:
    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="dummy.source",
            description="Dummy source.",
            input_model=DummySourceInput,
            handler=lambda args, context: {"value": "bad"},
            evidence_kinds=("dummy_value",),
            output_paths={
                "value": OutputPathContract(path="data.value", type="str"),
            },
        )
    )
    registry.register(
        ToolDefinition(
            name="dummy.consumer",
            description="Dummy consumer.",
            input_model=DummyConsumerInput,
            handler=lambda args, context: {"value": args.value},
            evidence_kinds=("dummy_value",),
            arg_contracts={
                "value": ArgContract(
                    accepts_refs=(
                        AcceptedRef(
                            from_tool="dummy.source",
                            path="data.value",
                            type="str",
                        ),
                    )
                )
            },
        )
    )
    errors = validate_registry_contracts(registry)

    assert any("is incompatible with input field int" in item for item in errors)


def test_registry_contracts_reject_unknown_arg_contract() -> None:
    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="dummy.source",
            description="Dummy source.",
            input_model=DummySourceInput,
            handler=lambda args, context: {"value": 1},
            arg_contracts={"missing": ArgContract(description="Bad metadata.")},
        )
    )

    errors = validate_registry_contracts(registry)

    assert "dummy.source arg_contracts reference unknown args: missing" in errors


def test_registry_contracts_reject_output_type_mismatch() -> None:
    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="dummy.source",
            description="Dummy source.",
            input_model=DummySourceInput,
            handler=lambda args, context: {"value": "bad"},
            output_paths={
                "value": OutputPathContract(path="data.value", type="str"),
            },
        )
    )
    registry.register(
        ToolDefinition(
            name="dummy.consumer",
            description="Dummy consumer.",
            input_model=DummyConsumerInput,
            handler=lambda args, context: {"value": args.value},
            arg_contracts={
                "value": ArgContract(
                    accepts_refs=(
                        AcceptedRef(
                            from_tool="dummy.source",
                            path="data.value",
                            type="int",
                        ),
                    )
                )
            },
        )
    )

    errors = validate_registry_contracts(registry)

    assert any(
        "does not match dummy.source output path data.value type str" in item
        for item in errors
    )


def test_contract_catalog_known_evidence_comes_from_registry() -> None:
    class DummyInput(BaseModel):
        query: str

    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="dummy.tool",
            description="Dummy tool.",
            input_model=DummyInput,
            handler=lambda args, context: {},
            evidence_kinds=("new_registry_evidence",),
        )
    )

    assert "new_registry_evidence" in known_evidence_kinds(registry)


def test_registry_contracts_fail_fast_on_invalid_evidence_declarations() -> None:
    class DummyInput(BaseModel):
        query: str

    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="dummy.tool",
            description="Invalid evidence metadata.",
            input_model=DummyInput,
            handler=lambda args, context: {},
            evidence_kinds=("declared_result",),
            mandatory_evidence=("undeclared_result",),
        )
    )

    errors = validate_registry_contracts(registry)

    assert any("mandatory_evidence is not declared" in item for item in errors)
    assert any("without an evidence_extractor" in item for item in errors)
    assert any("produces evidence without declaring source" in item for item in errors)
    assert any("contract patch_impact_report requires unknown evidence" in item for item in errors)


def test_controller_context_destination_rejects_evidence_declarations() -> None:
    class DummyInput(BaseModel):
        query: str

    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="dummy.context",
            description="Invalid context metadata.",
            input_model=DummyInput,
            handler=lambda args, context: {"messages": []},
            result_destination="controller_context",
            evidence_kinds=("invalid_context_evidence",),
        )
    )

    errors = validate_registry_contracts(registry)

    assert any(
        "routes results to controller_context" in item
        for item in errors
    )


def test_render_controller_contracts_contains_team_recent_fields() -> None:
    rendered = render_controller_contracts(_registry())

    assert "team_recent_report" in rendered
    assert "recent_matches" in rendered
    assert "current_players" in rendered
    assert "team_hero_usage" in rendered


def test_render_controller_contracts_omits_allowed_evidence_when_unrestricted() -> None:
    rendered = render_controller_contracts(_registry())

    # Unrestricted contracts (no allowlist) omit the line entirely.
    assert "allowed_evidence" not in _contract_section(
        rendered,
        "patch_impact_report",
    )
    # Restricted contracts still emit the allowed_evidence line.
    assert "allowed_evidence" in _contract_section(
        rendered,
        "team_recent_report",
    )


def test_render_controller_tools_contains_schema_and_reference_contracts() -> None:
    rendered = render_controller_tools(_registry())

    assert "evidence_produced" in rendered
    assert "- is_with: bool, required" in rendered
    assert "accepts_ref: resolve_hero.data.hero.hero_id (int)" in rendered
    assert "$<previous_call_id>.data.hero.hero_id" in rendered


def test_render_controller_tools_uses_generic_dummy_contracts() -> None:
    rendered = render_controller_tools(_dummy_registry())

    assert "dummy.source" in rendered
    assert "dummy_value" in rendered
    assert "- value: int, required" in rendered
    assert "accepts_ref: dummy.source.data.value (int)" in rendered
    assert "$<previous_call_id>.data.value" in rendered


def _contract_section(rendered: str, name: str) -> str:
    marker = f"- {name}"
    start = rendered.index(marker)
    next_start = rendered.find("\n- ", start + 1)
    if next_start == -1:
        return rendered[start:]
    return rendered[start:next_start]


class DummySourceInput(BaseModel):
    pass


class DummyConsumerInput(BaseModel):
    value: int


def _dummy_registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="dummy.source",
            description="Dummy source.",
            input_model=DummySourceInput,
            handler=lambda args, context: {"value": 1},
            evidence_kinds=("dummy_value",),
            output_paths={
                "value": OutputPathContract(
                    path="data.value",
                    type="int",
                    description="Dummy integer value.",
                ),
            },
        )
    )
    registry.register(
        ToolDefinition(
            name="dummy.consumer",
            description="Dummy consumer.",
            input_model=DummyConsumerInput,
            handler=lambda args, context: {"value": args.value},
            evidence_kinds=("dummy_value",),
            arg_contracts={
                "value": ArgContract(
                    description="Dummy value.",
                    accepts_refs=(
                        AcceptedRef(
                            from_tool="dummy.source",
                            path="data.value",
                            type="int",
                        ),
                    ),
                )
            },
        )
    )
    return registry


def test_validate_context_scope_enforces_weeks_back_cap() -> None:
    from app.agentic.models import QueryContext
    from app.agentic.planning.contracts import validate_context_scope
    from app.core.config import get_policy

    cap = get_policy().stratz.weeks_back_max

    def plan_with(weeks_back: int) -> ExecutionPlan:
        return ExecutionPlan(
            intent="x",
            goal="y",
            output_contract="natural_language_answer",
            context=QueryContext(weeks_back=weeks_back),
        )

    assert validate_context_scope(plan_with(1)) == []
    assert validate_context_scope(plan_with(cap)) == []
    errors = validate_context_scope(plan_with(cap + 1))
    assert len(errors) == 1
    assert "weeks_back" in errors[0]


def test_validate_context_scope_rejects_region_with_non_daily_tools() -> None:
    """region_ids/game_mode_ids are only supported by hero_daily_trends (schema).
    Handing them to other tools must surface as a validation error, not be
    silently ignored."""
    from app.agentic.models import QueryContext, ToolCall
    from app.agentic.planning.contracts import validate_context_scope

    plan = ExecutionPlan(
        intent="counter_pick",
        goal="eu west counter",
        output_contract="natural_language_answer",
        context=QueryContext(bracket=["DIVINE_IMMORTAL"], region_ids=["EUROPE"]),
        tool_calls=[
            ToolCall(
                id="t1", tool="stratz.hero_matchup_ranking", args={"hero_id": 1}
            )
        ],
        required_evidence=["matchup_ranking_row"],
    )
    errors = validate_context_scope(plan)
    assert any("region_ids" in e and "hero_daily_trends" in e for e in errors)


def test_validate_context_scope_allows_region_with_daily_trends_only() -> None:
    from app.agentic.models import QueryContext, ToolCall
    from app.agentic.planning.contracts import validate_context_scope

    plan = ExecutionPlan(
        intent="daily_trend",
        goal="eu trend",
        output_contract="natural_language_answer",
        context=QueryContext(region_ids=["EUROPE"]),
        tool_calls=[
            ToolCall(id="t1", tool="stratz.hero_daily_trends", args={"hero_id": 1})
        ],
        required_evidence=["hero_daily_trend"],
    )
    assert validate_context_scope(plan) == []


def test_validate_plan_accepts_list_dict_ref_without_min_length_error() -> None:
    """A list arg with min_length, populated via $ref, must not fail validation
    on an empty placeholder — the real value comes from the ref target at run
    time. Guards the filter_ranked_heroes_by_position candidate_rows contract."""
    from app.agentic.models import QueryContext, ToolCall
    from app.agentic.planning.contracts import validate_plan_against_catalog
    from app.agentic.tools.stratz_tools import build_default_tool_registry
    from app.core.config import get_settings

    registry = build_default_tool_registry(get_settings())
    plan = ExecutionPlan(
        intent="position_filtered_matchup",
        goal="4 号位克制 Lina",
        output_contract="natural_language_answer",
        context=QueryContext(),
        tool_calls=[
            ToolCall(id="resolve", tool="resolve_hero", args={"query": "Lina"}),
            ToolCall(
                id="matchup",
                tool="stratz.hero_matchup_ranking",
                args={"hero_id": "$resolve.data.hero.hero_id"},
            ),
            ToolCall(
                id="filter",
                tool="stratz.filter_ranked_heroes_by_position",
                args={
                    "candidate_rows": "$matchup.data.candidate_rows",
                    "position_id": "POSITION_4",
                },
            ),
        ],
        required_evidence=[
            "hero_identity",
            "matchup_ranking_row",
            "role_filtered_candidate_row",
        ],
    )
    errors = validate_plan_against_catalog(plan, registry)
    assert not any("too_short" in e or "candidate_rows" in e for e in errors)

    candidate_contract = registry.get(
        "stratz.filter_ranked_heroes_by_position"
    ).arg_contracts["candidate_rows"]
    assert candidate_contract.requires_reference is True

    literal_plan = plan.model_copy(deep=True)
    literal_plan.tool_calls[2].args["candidate_rows"] = [{"hero_id": 1}]
    literal_errors = validate_plan_against_catalog(literal_plan, registry)
    assert (
        "stratz.filter_ranked_heroes_by_position.candidate_rows must reference "
        "a previous current-plan tool result"
        in literal_errors
    )
