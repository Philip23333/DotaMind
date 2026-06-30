import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from types import UnionType
from typing import Any, Union, get_args, get_origin

from pydantic import ValidationError

from app.agentic.models import ExecutionPlan
from app.agentic.tools import ToolRegistry

NATURAL_LANGUAGE_CONTRACT = "natural_language_answer"


@dataclass(frozen=True)
class ContractSpec:
    name: str
    route: str
    required_evidence: frozenset[str] = field(default_factory=frozenset)
    allowed_required_evidence: frozenset[str] | None = None
    allowed_evidence: frozenset[str] | None = None
    required_tools: frozenset[str] = field(default_factory=frozenset)
    required_intent: str | None = None
    prompt_example: Mapping[str, Any] | None = None

    @property
    def structured(self) -> bool:
        return self.route == "structured"

    @property
    def evidence_allowlist(self) -> frozenset[str] | None:
        return self.allowed_evidence or self.allowed_required_evidence


CONTRACT_REGISTRY = {
    "patch_impact_report": ContractSpec(
        name="patch_impact_report",
        route="structured",
        required_evidence=frozenset({"patch_records"}),
        required_tools=frozenset({"patch.get_records"}),
    ),
    "role_meta_report": ContractSpec(
        name="role_meta_report",
        route="structured",
        required_evidence=frozenset({"hero_stats"}),
        allowed_evidence=frozenset({"hero_stats", "role_fit", "sample_size"}),
    ),
    "team_recent_report": ContractSpec(
        name="team_recent_report",
        route="structured",
        required_evidence=frozenset({"team_identity", "recent_matches"}),
        allowed_evidence=frozenset(
            {
                "team_identity",
                "recent_matches",
                "current_players",
                "team_hero_usage",
                "match_detail_sample",
                "sample_size",
            }
        ),
        prompt_example={
            "intent": "team_recent_performance",
            "goal": "Summarize a team's recent OpenDota evidence.",
            "output_contract": "team_recent_report",
            "tool_calls": [
                {
                    "id": "resolve_team",
                    "tool": "opendota.resolve_team",
                    "args": {"query": "<team query>"},
                },
                {
                    "id": "get_matches",
                    "tool": "opendota.team_recent_matches",
                    "args": {
                        "team_id": "$resolve_team.data.team.team_id",
                        "days": 30,
                    },
                },
                {
                    "id": "get_players",
                    "tool": "opendota.team_players",
                    "args": {
                        "team_id": "$resolve_team.data.team.team_id",
                        "current_only": True,
                    },
                },
                {
                    "id": "get_heroes",
                    "tool": "opendota.team_heroes",
                    "args": {"matches": "$get_matches.data.matches"},
                },
            ],
            "required_evidence": [
                "team_identity",
                "recent_matches",
                "current_players",
                "team_hero_usage",
            ],
            "constraints": {"max_tool_calls": 6, "allow_mock": False},
        },
    ),
    "hero_matchup_report": ContractSpec(
        name="hero_matchup_report",
        route="structured",
        required_evidence=frozenset({"matchup_win_rate"}),
    ),
    "draft_advice": ContractSpec(
        name="draft_advice",
        route="structured",
        required_evidence=frozenset(
            {"hero_identity", "matchup_win_rate", "sample_size"}
        ),
        required_intent="counter_pick",
    ),
    NATURAL_LANGUAGE_CONTRACT: ContractSpec(
        name=NATURAL_LANGUAGE_CONTRACT,
        route="natural_language",
    ),
}

STRUCTURED_OUTPUT_CONTRACTS = {
    name for name, spec in CONTRACT_REGISTRY.items() if spec.structured
}
ALLOWED_OUTPUT_CONTRACTS = set(CONTRACT_REGISTRY)


def get_contract(name: str) -> ContractSpec | None:
    return CONTRACT_REGISTRY.get(name)


def known_evidence_kinds(registry: ToolRegistry) -> set[str]:
    return {
        evidence_kind
        for definition in registry.list()
        for evidence_kind in definition.evidence_kinds
    }


def render_planner_contracts(registry: ToolRegistry) -> str:
    available_evidence = known_evidence_kinds(registry)
    sections = []
    for spec in CONTRACT_REGISTRY.values():
        allowed = spec.evidence_allowlist
        visible_allowed = sorted(allowed & available_evidence) if allowed else None
        sections.append(
            "\n".join(
                [
                    f"- {spec.name}",
                    f"  route: {spec.route}",
                    "  required_evidence: "
                    + json.dumps(sorted(spec.required_evidence)),
                    "  allowed_evidence: " + json.dumps(visible_allowed),
                    "  example: "
                    + (
                        json.dumps(spec.prompt_example, ensure_ascii=False)
                        if spec.prompt_example
                        else "null"
                    ),
                ]
            )
        )
    return "\n".join(sections)


def validate_plan_against_catalog(
    plan: ExecutionPlan,
    registry: ToolRegistry,
) -> list[str]:
    errors = validate_contract_plan_with_evidence(plan, known_evidence_kinds(registry))
    registered = {definition.name for definition in registry.list()}

    for call in plan.tool_calls:
        if call.tool not in registered:
            errors.append(f"unknown tool: {call.tool}")
            continue
        errors.extend(_validate_tool_args(call.tool, call.args, registry))

    if plan.constraints.allow_mock:
        errors.append("constraints.allow_mock must be false")
    if len(plan.tool_calls) > plan.constraints.max_tool_calls:
        errors.append(
            "plan exceeds max_tool_calls "
            f"({len(plan.tool_calls)} > {plan.constraints.max_tool_calls})"
        )

    if plan.intent == "counter_pick" and plan.output_contract != "draft_advice":
        errors.append("counter_pick plan must use output_contract=draft_advice")

    for call in plan.tool_calls:
        if call.tool in {"stratz.hero_vs_hero_matchup", "stratz.lane_outcome"}:
            hero_id = call.args.get("hero_id")
            if hero_id != "$resolve_target.data.hero.hero_id":
                errors.append(
                    f"{call.tool}.hero_id must be "
                    "$resolve_target.data.hero.hero_id"
                )

    return errors


def validate_contract_plan_with_evidence(
    plan: ExecutionPlan,
    evidence_kinds: set[str],
) -> list[str]:
    spec = get_contract(plan.output_contract)
    if spec is None:
        return [f"unknown output_contract: {plan.output_contract}"]

    errors: list[str] = []
    required = set(plan.required_evidence)
    unknown_evidence = sorted(required - evidence_kinds)
    if unknown_evidence:
        errors.append("unknown required_evidence: " + ", ".join(unknown_evidence))

    if spec.required_intent is not None and plan.intent != spec.required_intent:
        errors.append(
            f"{plan.output_contract} plan must use intent={spec.required_intent}"
        )

    missing = sorted(spec.required_evidence - required)
    if missing:
        errors.append(
            f"{plan.output_contract} plan missing required evidence: "
            + ", ".join(missing)
        )

    allowlist = spec.evidence_allowlist
    if allowlist is not None:
        invalid = sorted(required - allowlist)
        if invalid:
            errors.append(
                f"{plan.output_contract} required_evidence must use only "
                + ", ".join(sorted(allowlist))
                + "; got "
                + ", ".join(invalid)
            )

    tools = {call.tool for call in plan.tool_calls}
    missing_tools = sorted(spec.required_tools - tools)
    if missing_tools:
        errors.append(
            f"{plan.output_contract} plan must use " + ", ".join(missing_tools)
        )

    return errors


def _validate_tool_args(
    tool_name: str,
    args: dict[str, Any],
    registry: ToolRegistry,
) -> list[str]:
    definition = registry.get(tool_name)
    fields = definition.input_model.model_fields
    errors = []
    unknown = sorted(set(args) - set(fields))
    if unknown:
        errors.append(f"{tool_name} unknown args: " + ", ".join(unknown))
        return errors

    normalized = {
        name: _replace_references(value, fields[name].annotation)
        for name, value in args.items()
        if name in fields
    }
    try:
        definition.input_model.model_validate(normalized)
    except ValidationError as exc:
        errors.append(f"{tool_name} invalid args: {exc.errors()}")
    return errors


def _replace_references(value: Any, annotation: Any) -> Any:
    if isinstance(value, str) and value.startswith("$"):
        return _placeholder(annotation)
    if isinstance(value, dict):
        return {key: _replace_references(item, Any) for key, item in value.items()}
    if isinstance(value, list):
        return [_replace_references(item, Any) for item in value]
    return value


def _placeholder(annotation: Any) -> Any:
    origin = get_origin(annotation)
    if origin in {Union, UnionType}:
        non_none = [item for item in get_args(annotation) if item is not type(None)]
        return _placeholder(non_none[0]) if non_none else None
    if annotation is int:
        return 1
    if annotation is float:
        return 1.0
    if annotation is bool:
        return False
    if annotation is str:
        return "ref"
    if origin is list or annotation is list:
        return []
    if origin is dict or annotation is dict:
        return {}
    return "ref"
