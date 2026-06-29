from dataclasses import dataclass, field

from app.agentic.models import ExecutionPlan

NATURAL_LANGUAGE_CONTRACT = "natural_language_answer"


@dataclass(frozen=True)
class ContractSpec:
    name: str
    route: str
    required_evidence: frozenset[str] = field(default_factory=frozenset)
    allowed_required_evidence: frozenset[str] | None = None
    required_tools: frozenset[str] = field(default_factory=frozenset)
    required_intent: str | None = None

    @property
    def structured(self) -> bool:
        return self.route == "structured"


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
        allowed_required_evidence=frozenset({"hero_stats", "role_fit", "sample_size"}),
    ),
    "team_recent_report": ContractSpec(
        name="team_recent_report",
        route="structured",
        required_evidence=frozenset({"team_identity", "recent_matches"}),
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

    if spec.allowed_required_evidence is not None:
        invalid = sorted(required - spec.allowed_required_evidence)
        if invalid:
            errors.append(
                f"{plan.output_contract} required_evidence must use only "
                + ", ".join(sorted(spec.allowed_required_evidence))
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
