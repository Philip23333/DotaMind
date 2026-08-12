"""Controller decision contracts and deterministic validation helpers."""

from __future__ import annotations

import re
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
    *,
    current_query: str | None = None,
) -> list[str]:
    if isinstance(decision, DirectAnswerDecision):
        if current_query:
            missing_metrics = missing_historical_statistical_metrics(
                current_query,
                _history,
            )
            if missing_metrics:
                return [
                    "direct_answer is incomplete: historical conversation is missing "
                    f"requested metric(s): {', '.join(missing_metrics)}; choose tool_plan "
                    "and fetch them in the same decision"
                ]
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


_STATISTICAL_METRIC_TERMS = (
    "对线胜率",
    "整局胜率",
    "比赛胜率",
    "胜率",
    "负率",
    "平局率",
    "样本量",
    "出场率",
    "趋势",
    "lane win rate",
    "match win rate",
    "win rate",
    "loss rate",
    "draw rate",
    "sample size",
    "trend",
)
_STATISTICAL_VALUE_PATTERN = re.compile(
    r"(?:\d+(?:\.\d+)?\s*[％%]|\b\d+(?:\.\d+)?\b)"
)


def missing_historical_statistical_metrics(
    current_query: str,
    history: list[ConversationMessage],
) -> list[str]:
    """Return requested metric labels absent from history with an explicit value.

    This is a generic direct-answer completeness guard, not an intent router: it
    only rejects a direct answer when the current request names a statistical
    metric that the available conversation does not state numerically.
    """

    requested = _longest_metric_terms(current_query)
    if not requested or not history:
        return []
    historical_text = "\n".join(message.content for message in history)
    missing: list[str] = []
    for metric in requested:
        if metric.lower() not in historical_text.lower():
            missing.append(metric)
            continue
        metric_lines = [
            line
            for line in historical_text.splitlines()
            if metric.lower() in line.lower()
        ]
        if not any(_STATISTICAL_VALUE_PATTERN.search(line) for line in metric_lines):
            missing.append(metric)
    return missing


def _longest_metric_terms(text: str) -> list[str]:
    found = [term for term in _STATISTICAL_METRIC_TERMS if term.lower() in text.lower()]
    return [
        term
        for term in found
        if not any(
            term != other and term.lower() in other.lower()
            for other in found
        )
    ]
