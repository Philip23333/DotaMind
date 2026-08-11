"""Controller decision contracts and deterministic validation helpers."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.agentic.conversation.models import ConversationMessage
from app.agentic.models import ExecutionPlan
from app.agentic.planning.contracts import get_contract, validate_plan_against_catalog
from app.agentic.tools import ToolRegistry

ClarificationField = Annotated[
    str,
    StringConstraints(pattern=r"^[a-z][a-z0-9_]{0,63}$"),
]
NonEmptyAnswer = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=1000),
]


class StrictDecisionModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DirectAnswerDecision(StrictDecisionModel):
    kind: Literal["direct_answer"]
    intent: str = Field(min_length=1)
    answer: NonEmptyAnswer


class ClarificationDecision(StrictDecisionModel):
    kind: Literal["clarification"]
    intent: str = Field(min_length=1)
    question: str = Field(min_length=1, max_length=1000)
    missing_fields: list[ClarificationField] = Field(min_length=1, max_length=8)


class ContextMissingDecision(StrictDecisionModel):
    kind: Literal["context_missing"]
    intent: str = Field(min_length=1)
    reason: str = Field(min_length=1, max_length=1000)


class ToolPlanDecision(StrictDecisionModel):
    kind: Literal["tool_plan"]
    plan: ExecutionPlan


class CapabilityBoundaryDecision(StrictDecisionModel):
    kind: Literal["capability_boundary"]
    intent: str = Field(min_length=1)
    reason: str = Field(min_length=1, max_length=1000)


ControllerDecision = Annotated[
    DirectAnswerDecision
    | ClarificationDecision
    | ContextMissingDecision
    | ToolPlanDecision
    | CapabilityBoundaryDecision,
    Field(discriminator="kind"),
]


class DirectAnswerResult(BaseModel):
    answer_type: Literal["direct_answer"] = "direct_answer"
    status: Literal["ok"] = "ok"
    summary: str


class RequiredEvidenceResolution(BaseModel):
    planner_required_evidence: list[str] = Field(default_factory=list)
    global_required_evidence: list[str] = Field(default_factory=list)
    effective_required_evidence: list[str] = Field(default_factory=list)
    required_evidence_sources: dict[str, list[str]] = Field(default_factory=dict)
    mandatory_evidence_by_call: dict[str, list[str]] = Field(default_factory=dict)


def decision_intent(decision: ControllerDecision) -> str:
    if isinstance(decision, ToolPlanDecision):
        return decision.plan.intent
    return decision.intent


def resolve_required_evidence(
    plan: ExecutionPlan,
    registry: ToolRegistry,
) -> RequiredEvidenceResolution:
    """Merge contract, registry, and model-requested evidence without mutation."""
    sources: dict[str, set[str]] = {}
    global_required: set[str] = set(plan.required_evidence)
    mandatory_by_call: dict[str, list[str]] = {}

    contract = get_contract(plan.output_contract)
    if contract is not None:
        for kind in contract.required_evidence:
            sources.setdefault(kind, set()).add(f"contract:{contract.name}")
            global_required.add(kind)

    registered = {definition.name for definition in registry.list()}
    for call in plan.tool_calls:
        if call.tool not in registered:
            continue
        mandatory = sorted(set(registry.get(call.tool).mandatory_evidence))
        if mandatory:
            mandatory_by_call[call.id] = mandatory
        for kind in mandatory:
            sources.setdefault(kind, set()).add(f"tool:{call.tool}")

    for kind in plan.required_evidence:
        sources.setdefault(kind, set()).add("planner")

    stable_sources = {
        kind: sorted(values)
        for kind, values in sorted(sources.items())
    }
    return RequiredEvidenceResolution(
        planner_required_evidence=sorted(set(plan.required_evidence)),
        global_required_evidence=sorted(global_required),
        effective_required_evidence=sorted(stable_sources),
        required_evidence_sources=stable_sources,
        mandatory_evidence_by_call=dict(sorted(mandatory_by_call.items())),
    )


def normalize_controller_decision(decision: ControllerDecision) -> ControllerDecision:
    """Return a deterministic copy for stable validation, rendering, and debug."""
    if isinstance(decision, ClarificationDecision):
        return decision.model_copy(
            update={
                "missing_fields": sorted(set(decision.missing_fields)),
            }
        )
    return decision


def validate_controller_decision(
    decision: ControllerDecision,
    _history: list[ConversationMessage],
    registry: ToolRegistry,
    evidence: RequiredEvidenceResolution | None = None,
) -> list[str]:
    if isinstance(decision, DirectAnswerDecision):
        return []
    if isinstance(decision, ClarificationDecision):
        if not decision.missing_fields:
            return ["clarification requires at least one missing field"]
        return []
    if isinstance(decision, ToolPlanDecision):
        if not decision.plan.tool_calls:
            return ["tool_plan requires at least one tool call"]
        history_lookup_calls = [
            call for call in decision.plan.tool_calls if call.tool == "conversation.history_lookup"
        ]
        if history_lookup_calls:
            errors: list[str] = []
            if len(decision.plan.tool_calls) != 1:
                errors.append(
                    "conversation.history_lookup must be the only tool call in its plan"
                )
            if decision.plan.required_evidence:
                errors.append(
                    "conversation.history_lookup plans must not request required_evidence"
                )
            if errors:
                return errors
        required = evidence or resolve_required_evidence(decision.plan, registry)
        return validate_plan_against_catalog(
            decision.plan,
            registry,
            required_evidence=required.effective_required_evidence,
        )
    return []
