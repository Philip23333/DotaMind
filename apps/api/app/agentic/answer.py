import logging
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.agentic.evidence import EvidenceGraph, EvidenceItem
from app.agentic.models import ExecutionPlan
from app.agentic.planner import STRUCTURED_OUTPUT_CONTRACTS
from app.core.config import get_policy, get_settings
from app.llm.provider import LLMProvider, get_llm_provider

logger = logging.getLogger(__name__)

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
    ) -> AnswerSynthesisResult:
        structured = plan.output_contract in STRUCTURED_OUTPUT_CONTRACTS
        logger.info(
            "AnswerSynthesizer route output_contract=%s structured_contract=%s",
            plan.output_contract,
            structured,
        )
        if structured:
            logger.info("AnswerSynthesizer using StructuredReportSynthesizer")
            return self.structured.synthesize(plan, graph)
        if plan.output_contract == "natural_language_answer":
            logger.info("AnswerSynthesizer using NaturalLanguageAnswerSynthesizer")
            return await self.natural.synthesize(plan, graph)
        return unsupported_contract(plan, graph)


class StructuredReportSynthesizer:
    def synthesize(
        self,
        plan: ExecutionPlan,
        graph: EvidenceGraph,
    ) -> AnswerSynthesisResult:
        if plan.output_contract == "draft_advice":
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
                    data_notes=data_notes(graph),
                    confidence=0.0,
                )
            return self._counter_pick_answer(plan, graph)
        if plan.output_contract == "patch_impact_report":
            return self._patch_impact_report(plan, graph)
        if plan.output_contract == "role_meta_report":
            return self._role_meta_report(plan, graph)
        if plan.output_contract == "team_recent_report":
            return self._team_recent_report(plan, graph)
        if plan.output_contract == "hero_matchup_report":
            return self._hero_matchup_report(plan, graph)
        return unsupported_contract(plan, graph)

    def _patch_impact_report(
        self,
        plan: ExecutionPlan,
        graph: EvidenceGraph,
    ) -> AnswerSynthesisResult:
        records = items(graph, "patch_records")
        if graph.missing or not records:
            return insufficient(plan, graph, "Patch impact report needs patch_records evidence.")
        patch = records[0]
        hero = first_item(graph, "hero_patch_changes")
        item = first_item(graph, "item_patch_changes")
        claims = [
            AnswerClaim(
                claim=(
                    f"Patch {patch.value.get('patch')} has "
                    f"{patch.value.get('change_count')} recorded changes."
                ),
                evidence_refs=[patch.id],
            )
        ]
        if hero:
            claims.append(
                AnswerClaim(
                    claim=(
                        f"Hero changes: {hero.value.get('change_count')} changes "
                        f"across {hero.value.get('hero_count')} heroes."
                    ),
                    evidence_refs=[hero.id],
                )
            )
        if item:
            claims.append(
                AnswerClaim(
                    claim=f"Item-related changes: {item.value.get('change_count')} changes.",
                    evidence_refs=[item.id],
                )
            )
        return AnswerSynthesisResult(
            answer_type=plan.output_contract,
            status="ok",
            summary=f"Patch {patch.value.get('patch')} impact data is available.",
            claims=claims,
            limitations=[
                AnswerLimitation(
                    code="minimal_report",
                    detail=(
                        "This is a first-pass structured patch summary, not a "
                        "full impact ranking."
                    ),
                )
            ],
            data_notes=data_notes(graph),
            confidence=confidence(graph, has_output=True),
        )

    def _role_meta_report(
        self,
        plan: ExecutionPlan,
        graph: EvidenceGraph,
    ) -> AnswerSynthesisResult:
        stats = first_item(graph, "hero_stats")
        if graph.missing or not stats:
            return insufficient(plan, graph, "Role meta report needs hero_stats evidence.")
        heroes = stats.value.get("heroes", [])[:5]
        recommendations = [
            AnswerRecommendation(
                subject=str(hero.get("localized_name") or hero.get("hero_id")),
                recommendation_type="role_meta_candidate",
                score=hero.get("win_rate") or hero.get("pro_win_rate"),
                evidence_refs=[stats.id],
                rationale="Selected from OpenDota role-filtered hero stats.",
            )
            for hero in heroes
            if isinstance(hero, dict)
        ]
        return AnswerSynthesisResult(
            answer_type=plan.output_contract,
            status="ok" if recommendations else "insufficient_evidence",
            summary=f"Found {len(recommendations)} role meta candidates.",
            recommendations=recommendations,
            limitations=[
                AnswerLimitation(
                    code="minimal_report",
                    detail=(
                        "This ranks available role-filtered rows only; it does "
                        "not yet combine patch or lane context."
                    ),
                )
            ],
            data_notes=data_notes(graph),
            confidence=confidence(graph, has_output=bool(recommendations)),
        )

    def _team_recent_report(
        self,
        plan: ExecutionPlan,
        graph: EvidenceGraph,
    ) -> AnswerSynthesisResult:
        team = first_item(graph, "team_identity")
        matches = first_item(graph, "recent_matches")
        if graph.missing or not team or not matches:
            return insufficient(
                plan,
                graph,
                "Team recent report needs team_identity and recent_matches evidence.",
            )
        return AnswerSynthesisResult(
            answer_type=plan.output_contract,
            status="ok",
            summary=(
                f"{team.subject}: {matches.value.get('recent_record')} "
                f"over {matches.value.get('days')} days."
            ),
            claims=[
                AnswerClaim(
                    claim=f"Resolved team as {team.subject}.",
                    evidence_refs=[team.id],
                ),
                AnswerClaim(
                    claim=f"Recent record: {matches.value.get('recent_record')}.",
                    evidence_refs=[matches.id],
                ),
            ],
            limitations=[
                AnswerLimitation(
                    code="minimal_report",
                    detail=(
                        "This is evidence summary only; full tactical team "
                        "analysis is not migrated yet."
                    ),
                )
            ],
            data_notes=data_notes(graph),
            confidence=confidence(graph, has_output=True),
        )

    def _hero_matchup_report(
        self,
        plan: ExecutionPlan,
        graph: EvidenceGraph,
    ) -> AnswerSynthesisResult:
        matchups = items(graph, "matchup_win_rate")
        if graph.missing or not matchups:
            return insufficient(plan, graph, "Hero matchup report needs matchup_win_rate evidence.")
        recommendations = [
            AnswerRecommendation(
                subject=f"hero_id={item.value.get('hero_id')}",
                recommendation_type=str(item.value.get("side") or "matchup"),
                score=item.value.get("win_rate"),
                evidence_refs=[item.id],
                rationale="Selected from STRATZ hero matchup evidence.",
            )
            for item in matchups
        ]
        return AnswerSynthesisResult(
            answer_type=plan.output_contract,
            status="ok",
            summary=f"Found {len(recommendations)} hero matchup rows.",
            recommendations=recommendations,
            limitations=[
                AnswerLimitation(
                    code="hero_name_unresolved",
                    detail="Matchup rows currently expose hero_id values.",
                )
            ],
            data_notes=data_notes(graph),
            confidence=confidence(graph, has_output=True),
        )

    def _counter_pick_answer(
        self,
        plan: ExecutionPlan,
        graph: EvidenceGraph,
    ) -> AnswerSynthesisResult:
        if graph.missing:
            return AnswerSynthesisResult(
                answer_type=plan.output_contract,
                status="insufficient_evidence",
                summary=(
                    "Counter-pick answer cannot be completed because required "
                    "evidence is missing."
                ),
                claims=hero_identity_claims(graph),
                limitations=missing_limitations(graph),
                data_notes=data_notes(graph),
                confidence=confidence(graph, has_output=False),
            )
        recommendations = [
            AnswerRecommendation(
                subject=f"hero_id={item.value.get('hero_id')}",
                recommendation_type=str(item.value.get("side") or "matchup"),
                score=item.value.get("win_rate"),
                evidence_refs=[item.id],
                rationale=(
                    "This candidate comes from STRATZ hero-vs-hero matchup evidence. "
                    "It is not a full draft recommendation."
                ),
            )
            for item in items(graph, "matchup_win_rate")
        ]
        limitations = [
            AnswerLimitation(
                code="not_full_draft_recommendation",
                detail=(
                    "Current tools provide matchup rows only. The answer does not yet "
                    "include role fit, team composition, synergy, or patch context."
                ),
            ),
            AnswerLimitation(
                code="hero_name_unresolved",
                detail="Matchup rows currently expose hero_id values.",
            ),
        ]
        if not recommendations:
            limitations.append(
                AnswerLimitation(
                    code="no_matchup_candidates",
                    detail="No matchup rows were available to produce candidate items.",
                )
            )
        return AnswerSynthesisResult(
            answer_type=plan.output_contract,
            status="ok" if recommendations else "insufficient_evidence",
            summary=counter_pick_summary(graph, recommendations),
            claims=hero_identity_claims(graph),
            recommendations=recommendations,
            limitations=limitations,
            data_notes=data_notes(graph),
            confidence=confidence(graph, has_output=bool(recommendations)),
        )


class NaturalLanguageAnswerSynthesizer:
    def __init__(self, llm: LLMProvider | None, llm_enabled: bool) -> None:
        self.llm = llm
        self.llm_enabled = llm_enabled
        self.policy = get_policy()

    async def synthesize(
        self,
        plan: ExecutionPlan,
        graph: EvidenceGraph,
    ) -> AnswerSynthesisResult:
        if not self.llm_enabled or self.llm is None:
            return AnswerSynthesisResult(
                answer_type=plan.output_contract,
                status="error",
                summary="Natural language answer requires the LLM provider to be enabled.",
                limitations=[
                    AnswerLimitation(
                        code="llm_disabled",
                        detail="METAMIND_LLM_ENABLED must be true for natural_language_answer.",
                    )
                ],
                data_notes=data_notes(graph),
                confidence=0.0,
            )

        logger.info("NaturalLanguageAnswerSynthesizer start evidence=%s", len(graph.evidence))
        try:
            summary = await self.llm.complete(
                [
                    {
                        "role": "system",
                        "content": (
                            "You write concise evidence-grounded Dota 2 answers. "
                            "Use only the provided evidence graph. Do not invent stats. "
                            "If the evidence is insufficient, say exactly what is missing."
                        ),
                    },
                    {
                        "role": "user",
                        "content": (
                            f"goal={plan.goal}\n"
                            f"required_evidence={plan.required_evidence}\n"
                            f"evidence_graph={graph.model_dump(mode='json')}"
                        ),
                    },
                ],
                temperature=self.policy.llm.orchestrator.temperature,
                max_tokens=max(self.policy.llm.orchestrator.max_tokens, 1200),
            )
            logger.info("NaturalLanguageAnswerSynthesizer complete")
            return AnswerSynthesisResult(
                answer_type=plan.output_contract,
                status="ok",
                summary=summary.strip(),
                limitations=missing_limitations(graph),
                data_notes=data_notes(graph),
                confidence=confidence(graph, has_output=bool(summary.strip())),
            )
        except Exception as exc:
            logger.warning("NaturalLanguageAnswerSynthesizer failed: %r", exc)
            return AnswerSynthesisResult(
                answer_type=plan.output_contract,
                status="error",
                summary="Natural language answer synthesis failed.",
                limitations=[
                    AnswerLimitation(
                        code="llm_error",
                        detail=f"{type(exc).__name__}: {exc}",
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


def hero_identity_claims(graph: EvidenceGraph) -> list[AnswerClaim]:
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


def items(graph: EvidenceGraph, kind: str) -> list[EvidenceItem]:
    return [item for item in graph.evidence if item.kind == kind]


def first_item(graph: EvidenceGraph, kind: str) -> EvidenceItem | None:
    return next((item for item in graph.evidence if item.kind == kind), None)


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
    if graph.data_quality.min_sample_size is not None:
        notes.append(
            AnswerDataNote(
                code="minimum_sample_size",
                detail=f"Minimum observed sample size is {graph.data_quality.min_sample_size}.",
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


def counter_pick_summary(
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


def confidence(graph: EvidenceGraph, *, has_output: bool) -> float:
    value = graph.data_quality.completeness
    if graph.data_quality.mock_used:
        value = min(value, 0.2)
    if graph.data_quality.min_sample_size is not None:
        sample_factor = min(graph.data_quality.min_sample_size / 100, 1.0)
        value = min(value, 0.4 + sample_factor * 0.5)
    if not has_output:
        value = min(value, 0.35)
    return round(value, 2)
