from collections.abc import Callable
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.agentic.evidence import EvidenceGraph
from app.agentic.models import ExecutionPlan
from app.agentic.planning.contracts import (
    NATURAL_LANGUAGE_CONTRACT,
    get_contract,
)
from app.agentic.prompts.answer import render_natural_language_answer_messages
from app.agentic.runtime.streaming import (
    ObserverStreamEvent,
    current_observer_attempt_index,
    observer_events_enabled,
    publish_observer_event,
)
from app.core.config import get_policy, get_settings
from app.llm.provider import LLMProvider, get_llm_provider

AnswerStatus = Literal[
    "ok",
    "insufficient_evidence",
    "unsupported_output_contract",
    "error",
]


class AnswerClaim(BaseModel):
    claim: str
    evidence_refs: list[str] = Field(default_factory=list)


class AnswerRecommendation(BaseModel):
    subject: str
    recommendation_type: str
    score: float | None = None
    evidence_refs: list[str] = Field(default_factory=list)
    rationale: str


class AnswerLimitation(BaseModel):
    code: str
    detail: str


class AnswerDataNote(BaseModel):
    code: str
    detail: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class AnswerSynthesisResult(BaseModel):
    answer_type: str
    status: AnswerStatus
    summary: str
    claims: list[AnswerClaim] = Field(default_factory=list)
    recommendations: list[AnswerRecommendation] = Field(default_factory=list)
    limitations: list[AnswerLimitation] = Field(default_factory=list)
    data_notes: list[AnswerDataNote] = Field(default_factory=list)
    confidence: float = Field(ge=0, le=1)


class AnswerSynthesizer:
    """Routes evidence to structured or natural-language answer synthesis."""

    def __init__(
        self,
        *,
        llm: LLMProvider | None = None,
        llm_enabled: bool | None = None,
    ) -> None:
        settings = get_settings()
        self.llm_enabled = settings.llm_enabled if llm_enabled is None else llm_enabled
        self.llm = llm
        if self.llm is None and self.llm_enabled:
            self.llm = get_llm_provider()
        self.structured = StructuredReportSynthesizer()
        self.natural = NaturalLanguageAnswerSynthesizer(self.llm, self.llm_enabled)

    async def synthesize(
        self,
        plan: ExecutionPlan,
        graph: EvidenceGraph,
        *,
        current_query: str | None = None,
        on_delta: Callable[[str], None] | None = None,
    ) -> AnswerSynthesisResult:
        contract = get_contract(plan.output_contract)
        if contract is not None and contract.name == NATURAL_LANGUAGE_CONTRACT:
            return await self.natural.synthesize(
                plan,
                graph,
                current_query=current_query,
                on_delta=on_delta,
            )
        return unsupported_contract(plan, graph)


class StructuredReportSynthesizer:
    def synthesize(
        self,
        plan: ExecutionPlan,
        graph: EvidenceGraph,
    ) -> AnswerSynthesisResult:
        return unsupported_contract(plan, graph)


class NaturalLanguageAnswerSynthesizer:
    def __init__(self, llm: LLMProvider | None, llm_enabled: bool) -> None:
        self.llm = llm
        self.llm_enabled = llm_enabled
        self.policy = get_policy()

    async def synthesize(
        self,
        plan: ExecutionPlan,
        graph: EvidenceGraph,
        *,
        current_query: str | None = None,
        on_delta: Callable[[str], None] | None = None,
    ) -> AnswerSynthesisResult:
        if not self.llm_enabled or self.llm is None:
            return AnswerSynthesisResult(
                answer_type=plan.output_contract,
                status="error",
                summary="Natural language answer requires the LLM provider to be enabled.",
                limitations=[
                    AnswerLimitation(
                        code="llm_disabled",
                        detail="DOTAMIND_LLM_ENABLED must be true for natural_language_answer.",
                    )
                ],
                data_notes=data_notes(graph),
                confidence=0.0,
            )

        try:
            messages = render_natural_language_answer_messages(
                plan,
                graph,
                current_query=current_query,
            )
            if observer_events_enabled():
                publish_observer_event(
                    ObserverStreamEvent(
                        kind="model_prompt",
                        stage="answer",
                        call_id="answer:0",
                        name="answer",
                        attempt_index=current_observer_attempt_index(),
                        payload={
                            "messages": [dict(message) for message in messages],
                            "temperature": self.policy.llm.orchestrator.temperature,
                            "max_tokens": max(
                                self.policy.llm.orchestrator.max_tokens,
                                1200,
                            ),
                        },
                    )
                )
            if on_delta is None:
                summary = await self.llm.complete(
                    messages,
                    temperature=self.policy.llm.orchestrator.temperature,
                    max_tokens=max(self.policy.llm.orchestrator.max_tokens, 1200),
                )
            else:
                chunks: list[str] = []
                async for delta in self.llm.stream_complete(
                    messages,
                    temperature=self.policy.llm.orchestrator.temperature,
                    max_tokens=max(self.policy.llm.orchestrator.max_tokens, 1200),
                ):
                    chunks.append(delta)
                    on_delta(delta)
                summary = "".join(chunks)
            summary = summary.strip()
            publish_observer_event(
                ObserverStreamEvent(
                    kind="model_output",
                    stage="answer",
                    call_id="answer:0",
                    name="answer",
                    attempt_index=current_observer_attempt_index(),
                    payload={"format": "text", "content": summary},
                )
            )
            return AnswerSynthesisResult(
                answer_type=plan.output_contract,
                status="ok",
                summary=summary,
                limitations=missing_limitations(graph),
                data_notes=data_notes(graph),
                confidence=confidence(graph, has_output=bool(summary)),
            )
        except Exception as exc:
            publish_observer_event(
                ObserverStreamEvent(
                    kind="model_output",
                    stage="answer",
                    call_id="answer:0",
                    name="answer",
                    attempt_index=current_observer_attempt_index(),
                    payload={
                        "format": "error",
                        "content": None,
                        "error": f"{type(exc).__name__}: {exc}",
                    },
                )
            )
            return AnswerSynthesisResult(
                answer_type=plan.output_contract,
                status="error",
                summary="Natural language answer synthesis failed.",
                limitations=[
                    AnswerLimitation(
                        code="llm_error",
                        detail="answer generation failed",
                    )
                ],
                data_notes=data_notes(graph),
                confidence=0.0,
            )


def unsupported_contract(plan: ExecutionPlan, graph: EvidenceGraph) -> AnswerSynthesisResult:
    return AnswerSynthesisResult(
        answer_type=plan.output_contract,
        status="unsupported_output_contract",
        summary="AnswerSynthesizer does not support this output contract.",
        limitations=[
            AnswerLimitation(
                code="unsupported_output_contract",
                detail=f"Unsupported output_contract={plan.output_contract}.",
            )
        ],
        data_notes=data_notes(graph),
        confidence=0.0,
    )


def insufficient(
    plan: ExecutionPlan,
    graph: EvidenceGraph,
    summary: str,
) -> AnswerSynthesisResult:
    return AnswerSynthesisResult(
        answer_type=plan.output_contract,
        status="insufficient_evidence",
        summary=summary,
        limitations=missing_limitations(graph),
        data_notes=data_notes(graph),
        confidence=confidence(graph, has_output=False),
    )


def missing_limitations(graph: EvidenceGraph) -> list[AnswerLimitation]:
    return [
        AnswerLimitation(
            code="missing_required_evidence",
            detail=f"Missing evidence: {missing}",
        )
        for missing in graph.missing
    ]


def data_notes(graph: EvidenceGraph) -> list[AnswerDataNote]:
    notes = [
        AnswerDataNote(
            code="evidence_completeness",
            detail=f"Evidence completeness is {graph.data_quality.completeness:.0%}.",
            metadata={"completeness": graph.data_quality.completeness},
        )
    ]
    if graph.data_quality.mock_used:
        notes.append(
            AnswerDataNote(
                code="mock_source_detected",
                detail="At least one tool result used a mocked source.",
                metadata={"mock_used": True},
            )
        )
    return notes


def confidence(graph: EvidenceGraph, *, has_output: bool) -> float:
    value = graph.data_quality.completeness
    if graph.data_quality.mock_used:
        value = min(value, 0.2)
    if not has_output:
        value = min(value, 0.35)
    return round(value, 2)
