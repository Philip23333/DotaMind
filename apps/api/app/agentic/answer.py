from typing import Any, Literal

from pydantic import BaseModel, Field

from app.agentic.evidence import EvidenceGraph, EvidenceItem
from app.agentic.models import ExecutionPlan

AnswerStatus = Literal["ok", "insufficient_evidence", "unsupported_output_contract"]


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
    """Turns plan evidence into structured answer claims without fetching data."""

    def synthesize(
        self,
        plan: ExecutionPlan,
        graph: EvidenceGraph,
    ) -> AnswerSynthesisResult:
        if plan.output_contract != "draft_advice":
            return AnswerSynthesisResult(
                answer_type=plan.output_contract,
                status="unsupported_output_contract",
                summary=(
                    "AnswerSynthesizer does not support this output contract yet."
                ),
                limitations=[
                    AnswerLimitation(
                        code="unsupported_output_contract",
                        detail=(
                            "Current AnswerSynthesizer only supports "
                            "output_contract='draft_advice'."
                        ),
                    )
                ],
                data_notes=self._data_notes(graph),
                confidence=0.0,
            )

        if plan.intent != "counter_pick":
            return AnswerSynthesisResult(
                answer_type=plan.output_contract,
                status="unsupported_output_contract",
                summary="Draft advice is currently only supported for counter_pick intent.",
                limitations=[
                    AnswerLimitation(
                        code="unsupported_intent",
                        detail=(
                            "Current draft_advice synthesis only supports "
                            "intent='counter_pick'."
                        ),
                    )
                ],
                data_notes=self._data_notes(graph),
                confidence=0.0,
            )

        return self._counter_pick_answer(plan, graph)

    def _counter_pick_answer(
        self,
        plan: ExecutionPlan,
        graph: EvidenceGraph,
    ) -> AnswerSynthesisResult:
        limitations = self._missing_limitations(graph)
        data_notes = self._data_notes(graph)
        if graph.missing:
            return AnswerSynthesisResult(
                answer_type=plan.output_contract,
                status="insufficient_evidence",
                summary=(
                    "Counter-pick answer cannot be completed because required "
                    "evidence is missing."
                ),
                claims=self._hero_identity_claims(graph),
                limitations=limitations,
                data_notes=data_notes,
                confidence=self._confidence(graph, has_recommendations=False),
            )

        matchup_items = self._matchup_items(graph)
        recommendations = [
            AnswerRecommendation(
                subject=f"hero_id={item.value.get('hero_id')}",
                recommendation_type=str(item.value.get("side") or "matchup"),
                score=item.value.get("win_rate"),
                evidence_refs=[item.id],
                rationale=(
                    "This candidate comes from STRATZ hero-vs-hero matchup "
                    "evidence. It is not a full draft recommendation."
                ),
            )
            for item in matchup_items
        ]
        if recommendations:
            limitations.append(
                AnswerLimitation(
                    code="not_full_draft_recommendation",
                    detail=(
                        "Current tools provide matchup rows only. The answer does "
                        "not yet include candidate pool filtering, player role fit, "
                        "team composition, synergy, or patch context."
                    ),
                )
            )
            limitations.append(
                AnswerLimitation(
                    code="hero_name_unresolved",
                    detail=(
                        "Matchup rows currently expose hero_id values. A hero_id "
                        "to hero name tool is not registered yet."
                    ),
                )
            )

        status: AnswerStatus = "ok" if recommendations else "insufficient_evidence"
        if not recommendations:
            limitations.append(
                AnswerLimitation(
                    code="no_matchup_candidates",
                    detail="No matchup rows were available to produce candidate items.",
                )
            )

        return AnswerSynthesisResult(
            answer_type=plan.output_contract,
            status=status,
            summary=self._counter_pick_summary(graph, recommendations),
            claims=self._hero_identity_claims(graph),
            recommendations=recommendations,
            limitations=limitations,
            data_notes=data_notes,
            confidence=self._confidence(graph, has_recommendations=bool(recommendations)),
        )

    @staticmethod
    def _hero_identity_claims(graph: EvidenceGraph) -> list[AnswerClaim]:
        claims = []
        for item in graph.evidence:
            if item.kind != "hero_identity":
                continue
            localized_name = item.value.get("localized_name") or item.subject
            hero_id = item.value.get("hero_id")
            claims.append(
                AnswerClaim(
                    claim=f"Resolved target hero as {localized_name} (hero_id={hero_id}).",
                    evidence_refs=[item.id],
                )
            )
        return claims

    @staticmethod
    def _matchup_items(graph: EvidenceGraph) -> list[EvidenceItem]:
        return [item for item in graph.evidence if item.kind == "matchup_win_rate"]

    @staticmethod
    def _missing_limitations(graph: EvidenceGraph) -> list[AnswerLimitation]:
        return [
            AnswerLimitation(
                code="missing_required_evidence",
                detail=f"Missing evidence: {missing}",
            )
            for missing in graph.missing
        ]

    @staticmethod
    def _data_notes(graph: EvidenceGraph) -> list[AnswerDataNote]:
        notes = [
            AnswerDataNote(
                code="evidence_completeness",
                detail=(
                    "Evidence completeness is "
                    f"{graph.data_quality.completeness:.0%}."
                ),
                metadata={"completeness": graph.data_quality.completeness},
            )
        ]
        if graph.data_quality.min_sample_size is not None:
            notes.append(
                AnswerDataNote(
                    code="minimum_sample_size",
                    detail=(
                        "Minimum observed matchup sample size is "
                        f"{graph.data_quality.min_sample_size}."
                    ),
                    metadata={"min_sample_size": graph.data_quality.min_sample_size},
                )
            )
        if graph.data_quality.mock_used:
            notes.append(
                AnswerDataNote(
                    code="mock_source_detected",
                    detail="At least one tool result used a mocked source.",
                    metadata={"mock_used": True},
                )
            )
        return notes

    @staticmethod
    def _counter_pick_summary(
        graph: EvidenceGraph,
        recommendations: list[AnswerRecommendation],
    ) -> str:
        hero_names = [
            item.value.get("localized_name") or item.subject
            for item in graph.evidence
            if item.kind == "hero_identity"
        ]
        target = str(hero_names[0]) if hero_names else "the target hero"
        if not recommendations:
            return f"Insufficient evidence to produce matchup candidates for {target}."
        return (
            f"Found {len(recommendations)} matchup candidate rows for {target}. "
            "These are evidence items, not a complete draft recommendation."
        )

    @staticmethod
    def _confidence(graph: EvidenceGraph, *, has_recommendations: bool) -> float:
        confidence = graph.data_quality.completeness
        if graph.data_quality.mock_used:
            confidence = min(confidence, 0.2)
        if graph.data_quality.min_sample_size is not None:
            sample_factor = min(graph.data_quality.min_sample_size / 100, 1.0)
            confidence = min(confidence, 0.4 + sample_factor * 0.5)
        if not has_recommendations:
            confidence = min(confidence, 0.35)
        return round(confidence, 2)
