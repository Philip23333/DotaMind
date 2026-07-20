"""Controller decision contracts and deterministic validation helpers."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.agentic.conversation.models import Turn
from app.agentic.models import ExecutionPlan
from app.agentic.planning.contracts import (
    CONTRACT_REGISTRY,
    ContractSpec,
    get_contract,
    validate_plan_against_catalog,
)
from app.agentic.tools import ToolRegistry

ClarificationField = Literal[
    "hero_query",
    "partner_hero_query",
    "team_query",
    "steam_account_id",
    "position_ids",
    "role",
    "patch",
    "bracket",
    "weeks_back",
    "region_ids",
    "game_mode_ids",
]
ConversationField = Literal["query", "response_summary", "resolved_entities"]
ConversationEntityType = Literal["hero", "team", "player"]
DirectResponseMode = Literal[
    "quote_user_query",
    "recall_entity",
    "recall_assistant_summary",
    "social",
]


class StrictDecisionModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ConversationBasis(StrictDecisionModel):
    turn_index: int = Field(ge=1)
    field: ConversationField
    entity_type: ConversationEntityType | None = None


class DirectAnswerDecision(StrictDecisionModel):
    kind: Literal["direct_answer"]
    intent: str = Field(min_length=1)
    response_mode: DirectResponseMode
    basis: list[ConversationBasis] = Field(default_factory=list)
    answer: str | None = Field(default=None, max_length=1000)


class ClarificationDecision(StrictDecisionModel):
    kind: Literal["clarification"]
    intent: str = Field(min_length=1)
    question: str = Field(min_length=1, max_length=1000)
    missing_fields: list[ClarificationField] = Field(min_length=1)


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


class ConversationAnswerResult(BaseModel):
    answer_type: Literal["direct_answer"] = "direct_answer"
    status: Literal["ok"] = "ok"
    summary: str
    conversation_basis: list[ConversationBasis] = Field(default_factory=list)


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
    contracts: Mapping[str, ContractSpec] = CONTRACT_REGISTRY,
) -> RequiredEvidenceResolution:
    """Merge contract, registry, and model-requested evidence without mutation."""
    sources: dict[str, set[str]] = {}
    global_required: set[str] = set(plan.required_evidence)
    mandatory_by_call: dict[str, list[str]] = {}

    contract = get_contract(plan.output_contract, contracts)
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
    if isinstance(decision, DirectAnswerDecision):
        unique = {
            (basis.turn_index, basis.field, basis.entity_type): basis
            for basis in decision.basis
        }
        keys = sorted(unique, key=lambda item: (item[0], item[1], item[2] or ""))
        basis = [unique[key] for key in keys]
        updates = {"basis": basis}
        if decision.response_mode != "social":
            updates["answer"] = None
        return decision.model_copy(update=updates)
    if isinstance(decision, ClarificationDecision):
        return decision.model_copy(update={"missing_fields": sorted(set(decision.missing_fields))})
    return decision


def validate_controller_decision(
    decision: ControllerDecision,
    history: list[Turn],
    registry: ToolRegistry,
    evidence: RequiredEvidenceResolution | None = None,
    contracts: Mapping[str, ContractSpec] = CONTRACT_REGISTRY,
) -> list[str]:
    if isinstance(decision, DirectAnswerDecision):
        return _validate_direct_answer(decision, history)
    if isinstance(decision, ClarificationDecision):
        if not decision.missing_fields:
            return ["clarification requires at least one missing field"]
        return []
    if isinstance(decision, ToolPlanDecision):
        if not decision.plan.tool_calls:
            return ["tool_plan requires at least one tool call"]
        required = evidence or resolve_required_evidence(
            decision.plan, registry, contracts
        )
        return validate_plan_against_catalog(
            decision.plan,
            registry,
            required_evidence=required.effective_required_evidence,
            contracts=contracts,
        )
    return []


def _validate_direct_answer(
    decision: DirectAnswerDecision,
    history: list[Turn],
) -> list[str]:
    errors: list[str] = []
    if decision.response_mode == "social":
        if decision.basis:
            errors.append("social direct answer must not reference conversation basis")
        if not decision.answer or not decision.answer.strip():
            errors.append("social direct answer requires answer text")
        return errors

    if decision.answer is not None:
        errors.append(
            'For conversation recall, set "answer" to JSON null; '
            "the server renders the final answer from the validated basis"
        )
    if not decision.basis:
        errors.append(f"{decision.response_mode} requires conversation basis")
        return errors

    expected_field = {
        "quote_user_query": "query",
        "recall_entity": "resolved_entities",
        "recall_assistant_summary": "response_summary",
    }[decision.response_mode]
    turns = {turn.turn_index: turn for turn in history}
    for basis in decision.basis:
        if basis.field != expected_field:
            errors.append(
                f"{decision.response_mode} basis must reference {expected_field}"
            )
            continue
        if basis.field != "resolved_entities" and basis.entity_type is not None:
            errors.append("entity_type is only valid for resolved_entities basis")
        turn = turns.get(basis.turn_index)
        if turn is None:
            errors.append(f"conversation turn is unavailable: {basis.turn_index}")
            continue
        if basis.field == "query" and not turn.query:
            errors.append(f"conversation turn {basis.turn_index} has empty query")
        elif basis.field == "response_summary":
            if turn.response_type == "session_request_failed":
                errors.append(
                    f"conversation turn {basis.turn_index} is a redacted failure"
                )
            elif not turn.response_summary:
                errors.append(
                    f"conversation turn {basis.turn_index} has empty response summary"
                )
        elif basis.field == "resolved_entities":
            if turn.status != "ok":
                errors.append(
                    f"conversation turn {basis.turn_index} is not eligible for entity recall"
                )
                continue
            entities = [
                entity
                for entity in turn.resolved_entities
                if basis.entity_type is None or entity.type == basis.entity_type
            ]
            if not entities:
                errors.append(
                    f"conversation turn {basis.turn_index} has no matching entities"
                )
    return errors
