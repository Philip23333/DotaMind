from collections.abc import Callable
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.agentic.evidence import EvidenceGraph, EvidenceItem
from app.agentic.models import ExecutionPlan
from app.agentic.planning.contracts import (
    NATURAL_LANGUAGE_CONTRACT,
    STRUCTURED_OUTPUT_CONTRACTS,
    get_contract,
)
from app.core.config import get_policy, get_settings
from app.llm.provider import LLMProvider, get_llm_provider

_NATURAL_LANGUAGE_SYSTEM_PROMPT = (
    "You write concise evidence-grounded Dota 2 answers. "
    "Use only the provided evidence graph. Do not invent stats. "
    "If the evidence is insufficient, say exactly what is missing. "
    "For Catalog facts, use only normalized text and values from "
    "hero_attributes, hero_ability, hero_talent_tree, item_definition, and "
    "item_recipe evidence. Distinguish base attribute values from per-level "
    "gains, and preserve ability level arrays instead of collapsing them into "
    "one number. Present talents by level 10/15/20/25 and left/right side. "
    "Distinguish normal abilities, innate abilities, Scepter grants/upgrades, "
    "and Shard grants/upgrades from their explicit flags and text. For items, "
    "distinguish the final item from a recipe item, components, and upgrade "
    "targets. Disclose the Catalog snapshot patch and generated_at carried by "
    "the evidence. When the user is asking for Catalog-backed hero, ability, "
    "talent, or item definitions, disclose the Catalog snapshot patch and "
    "generated_at carried by that Catalog evidence. Do not disclose Catalog "
    "patch/generated_at in an answer whose requested facts are STRATZ statistics, "
    "even when hero_identity Catalog evidence is also present. Catalog metadata "
    "must never be labeled as a STRATZ patch, statistics snapshot, or statistics "
    "version. Never infer item-build strength, skill leveling priority, "
    "talent win rate, popularity, or recommendations from static definitions. "
    "For a crafted item, render a Markdown table with columns `组件（中文名（English）） "
    "| 价格 | 属性`. Include every component and include the recipe scroll as an "
    "explicit row. Use each row's special_values/rendered display attributes; do "
    "not place Chinese and English names in mismatched columns. A recipe-scroll "
    "row with no display attributes may say `无`. Use cost_breakdown to verify and "
    "report the total price; explain a mismatch in natural language only when the "
    "calculated and finished-item prices differ, without exposing internal field "
    "names. If recipe_items evidence exists, "
    "never claim that the item has no recipe scroll. For a basic item, show only "
    "its name as `中文名（English）`, price, and attributes; do not invent a recipe "
    "table. "
    "User-visible answers must never expose internal schema or token names such "
    "as `has_shard = true`, `has_scepter`, `is_innate`, `special_bonus_*`, "
    "`talent_internal_name`, or `internal_name`. Translate explicit flags into "
    "natural headings such as 魔晶升级, 神杖升级, or 先天技能, without adding the "
    "internal field name in parentheses. Talent-bonus entries inside ability "
    "special_values must not create a separate 相关天赋 section and must not be "
    "shown as internal token references beside a value. "
    "For a complete hero ability-list query, start with the hero's Chinese and "
    "English names plus snapshot patch/generated_at. Then follow Catalog ability "
    "order and describe each ability with natural classification (normal, "
    "ultimate, innate, or sub-ability where supported), Chinese/English name, "
    "effect, levels, cast/cooldown/cost arrays, key values, and natural-language "
    "upgrades. Do not add separate 技能分类汇总 or 相关天赋 sections. End with a "
    "concise Markdown talent table whose columns include `等级 | 左侧天赋（中文 / "
    "English） | 右侧天赋（中文 / English）`. Do not repeat schema explanations. "
    "For a single-ability query, output only the one ability matching the user's "
    "name. Do not output other abilities, a classification summary, a related-"
    "talents section, or the full talent tree unless the user explicitly also "
    "asked for talents. "
    "When evidence items carry week_index/week_epoch (per-week STRATZ buckets), "
    "compare across weeks and state the trend (rising/falling/stable). "
    "If any requested week returned no sample (missing_week_epochs), say so "
    "explicitly. The default one-week STRATZ query is only the current query "
    "window, not a system limitation: say that multiple completed weeks can be "
    "queried when no cross-week comparison was requested. "
    "For pair_lane_outcome evidence, distinguish lane outcome from match outcome. "
    "Report lane_win_rate, lane_draw_rate, and lane_loss_rate using the supplied "
    "five-category lane counts, and report match_win_rate separately from "
    "match_win_count/match_count. When a pair lane query is present, include both "
    "the lane result and the match result by default. Use filters.position_ids "
    "as the only position scope; null means the query was not position-scoped. "
    "Never expose or interpret a raw response-row position as the requested lane. "
    "Catalog patch/generated_at metadata describes only Catalog snapshots and "
    "must not be presented as STRATZ statistics patch or snapshot metadata. "
    "Do not infer gameplay causes, comeback ability, mid-game strength, late-game "
    "strength, or causal explanations solely because match_win_rate differs from "
    "lane_win_rate. Report the statistical difference directly. If offering an "
    "interpretation not supported by explicit evidence, label it clearly as a "
    "hypothesis and do not present it as a conclusion. "
    "Hero recommendations are ranked by `wilson_rating` — the Wilson lower "
    "bound of the win rate (z=1.96, confidence-aware; STRATZ documents this as "
    "its trends rating method, z assumed 95% CI). Treat it as the primary "
    "signal: lead with the highest-wilson_rating rows and name it as the basis. "
    "When lane_meta_row/position_stat evidence carries filters.selection_mode, "
    "phrase the ranking basis to match it: 'strong' = top rows ranked by "
    "wilson_rating after the sample-size floor (say so, e.g. \"按 Wilson 评分"
    "(置信度加权胜率) 排序的前 K 个\"); 'popular' = ranked by pick volume. Always "
    "state the sample floor (filters.min_sample_size) and that only completed "
    "weeks count. "
    "For counter/synergy recommendations (matchup_ranking_row / "
    "hero_synergy_ranking_row), the PRIMARY ranking is STRATZ `synergy` — keep "
    "it first. `pair_wilson_rating` is a sample-confidence CO-SIGNAL: among "
    "comparable synergy prefer higher pair_wilson_rating, and flag low "
    "pair_wilson_rating as small-sample/uncertain. Do NOT merge synergy and "
    "pair_wilson_rating into a single composite score. "
    "When hero_daily_trend evidence is present (per-day STRATZ buckets, "
    "filters.grain == 'day'), describe the trend across calendar days, not "
    "weeks — name days/dates and the day-level win_rate direction; do not "
    "invent week buckets. day evidence uses win_rate_basis 'day: "
    "winCount/matchCount'."
)

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
        on_delta: Callable[[str], None] | None = None,
    ) -> AnswerSynthesisResult:
        structured = plan.output_contract in STRUCTURED_OUTPUT_CONTRACTS
        contract = get_contract(plan.output_contract)
        if structured:
            return self.structured.synthesize(plan, graph)
        if contract is not None and contract.name == NATURAL_LANGUAGE_CONTRACT:
            return await self.natural.synthesize(plan, graph, on_delta=on_delta)
        return unsupported_contract(plan, graph)


class StructuredReportSynthesizer:
    def synthesize(
        self,
        plan: ExecutionPlan,
        graph: EvidenceGraph,
    ) -> AnswerSynthesisResult:
        if plan.output_contract == "patch_impact_report":
            return self._patch_impact_report(plan, graph)
        if plan.output_contract == "role_meta_report":
            return self._role_meta_report(plan, graph)
        if plan.output_contract == "team_recent_report":
            return self._team_recent_report(plan, graph)
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
            messages = [
                {"role": "system", "content": _NATURAL_LANGUAGE_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": (
                        f"goal={plan.goal}\n"
                        f"required_evidence={graph.required_evidence}\n"
                        f"evidence_graph={graph.model_dump(mode='json')}"
                    ),
                },
            ]
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
            summary = _enforce_pair_lane_boundaries(summary.strip(), graph)
            return AnswerSynthesisResult(
                answer_type=plan.output_contract,
                status="ok",
                summary=summary,
                limitations=missing_limitations(graph),
                data_notes=data_notes(graph),
                confidence=confidence(graph, has_output=bool(summary)),
            )
        except Exception:
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


def _enforce_pair_lane_boundaries(summary: str, graph: EvidenceGraph) -> str:
    """Remove unsupported metadata/causal claims from pair-lane answers.

    Prompt rules are the primary control. This deterministic postcondition keeps
    a stochastic answer provider from leaking Catalog snapshot metadata or
    turning a lane/match rate difference into a gameplay conclusion.
    """

    if not items(graph, "pair_lane_outcome"):
        return summary

    catalog_values: set[str] = set()
    for item in items(graph, "hero_identity"):
        snapshot = item.value.get("snapshot")
        if not isinstance(snapshot, dict):
            continue
        for key in ("patch", "generated_at"):
            value = snapshot.get(key)
            if value:
                catalog_values.add(str(value))

    causal_markers = (
        "中后期",
        "中期",
        "后期",
        "翻盘",
        "mid-game",
        "late-game",
        "comeback",
        "causal explanation",
    )
    metadata_markers = tuple(catalog_values) + (
        "快照版本",
        "Catalog snapshot",
        "statistics snapshot",
        "statistics version",
    )
    removed_causal = False
    kept: list[str] = []
    for line in summary.splitlines():
        if any(marker.lower() in line.lower() for marker in causal_markers):
            removed_causal = True
            continue
        if any(marker.lower() in line.lower() for marker in metadata_markers):
            continue
        kept.append(line)

    result = "\n".join(kept).strip()
    if removed_causal:
        result = (
            f"{result}\n\n"
            "当前汇总数据只能说明对线结果与整局胜率存在差异，"
            "不能据此判断具体比赛阶段或后续表现。"
        ).strip()
    return result


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
