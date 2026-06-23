import asyncio
import logging
from typing import Any

from app.core.config import get_policy, get_settings
from app.domain.evidence import EvidenceBundle, EvidenceItem, Verdict
from app.domain.reports import (
    ClaimVerificationReport,
    HeroRecommendation,
    PatchImpactReport,
    TeamDataFreshness,
    TeamReport,
)
from app.llm.prompts import render_prompt
from app.llm.provider import get_llm_provider
from app.pipeline.retriever import summarize_patch_records

logger = logging.getLogger(__name__)


class AnalyzerAgent:
    """Turns evidence bundles into report-ready claims and report sections."""

    def __init__(self, use_llm: bool = True) -> None:
        settings = get_settings()
        self.policy = get_policy()
        self.llm_enabled = settings.llm_enabled and use_llm
        self.llm = None
        if self.llm_enabled:
            try:
                self.llm = get_llm_provider()
            except Exception as exc:
                logger.warning("LLM provider unavailable, analyzer stays deterministic: %s", exc)
                self.llm_enabled = False

    async def analyze_meta(self, bundle: EvidenceBundle, role: str) -> list[HeroRecommendation]:
        records = bundle.records[: self.policy.hero_report.result_limit]
        heroes = await asyncio.gather(
            *(self._hero_recommendation(record, role) for record in records)
        )
        heroes = list(heroes)
        heroes.sort(key=lambda item: item.meta_score, reverse=True)
        return heroes

    def analyze_patch(self, bundle: EvidenceBundle, game: str, patch: str) -> PatchImpactReport:
        patch_policy = self.policy.patch_report
        summary = summarize_patch_records(
            bundle.records,
            patch,
            neutral_score=patch_policy.neutral_score,
            change_delta=patch_policy.change_delta,
            result_limit=patch_policy.result_limit,
        )
        confidence = (
            0.4 if bundle.data_source == "mock" else min(0.9, 0.6 + len(bundle.records) * 0.002)
        )
        return PatchImpactReport(
            report_type="patch_impact",
            game=game,
            patch=str(summary["patch"]),
            summary=str(summary["summary"]),
            winners=[str(item) for item in summary["winners"]],
            losers=[str(item) for item in summary["losers"]],
            item_impacts=[str(item) for item in summary["item_impacts"]],
            lineup_trends=[str(item) for item in summary["lineup_trends"]],
            practice_advice=[str(item) for item in summary["practice_advice"]],
            sources=[],
            confidence=round(confidence, 2),
        )

    def analyze_team(
        self, bundle: EvidenceBundle, game: str, team_name: str, time_range: str
    ) -> TeamReport:
        data = bundle.records[0] if bundle.records else {}
        signature_heroes = [str(item) for item in data.get("signature_heroes", [])]
        recent_record = str(data.get("recent_record", "No recent matches available"))
        if "recent_win_rate" in data:
            confidence = round(
                min(
                    0.85,
                    0.5
                    + float(data["recent_win_rate"]) * 0.3
                    + float(data.get("draft_flexibility", 0)) * 0.2,
                ),
                2,
            )
        else:
            confidence = 0.4
        return TeamReport(
            report_type="team_report",
            game=game,
            team_name=str(data.get("team_name") or team_name),
            time_range=time_range,
            summary=str(
                data.get("summary")
                or f"{team_name} report is based on available team and draft signals."
            ),
            recent_record=recent_record,
            matches_in_window=int(data.get("matches_in_window", 0)),
            match_details_analyzed=int(data.get("match_details_analyzed", 0)),
            data_freshness=self._team_data_freshness(data),
            signature_heroes=signature_heroes,
            draft_preferences=[str(item) for item in data.get("draft_preferences", [])],
            win_patterns=[str(item) for item in data.get("win_patterns", [])]
            or ["No clear win pattern identified."],
            loss_patterns=[str(item) for item in data.get("loss_patterns", [])]
            or ["No clear loss pattern identified."],
            patch_adaptation_score=int(data.get("patch_adaptation_score", 40)),
            key_players=[str(item) for item in data.get("key_players", [])] or signature_heroes[:3],
            sources=[],
            confidence=confidence,
        )

    @staticmethod
    def _team_data_freshness(data: dict[str, Any]) -> TeamDataFreshness:
        freshness = data.get("data_freshness") or {}
        return TeamDataFreshness(
            latest_match_time=freshness.get("latest_match_time"),
            latest_match_at=freshness.get("latest_match_at"),
            sample_window_days=int(freshness.get("sample_window_days", 0)),
            matches_in_window=int(
                freshness.get("matches_in_window", data.get("matches_in_window", 0))
            ),
            match_details_analyzed=int(
                freshness.get(
                    "match_details_analyzed",
                    data.get("match_details_analyzed", 0),
                )
            ),
            opendota_cache_hits=int(freshness.get("opendota_cache_hits", 0)),
            opendota_cache_misses=int(freshness.get("opendota_cache_misses", 0)),
        )

    def analyze_claim(
        self, bundle: EvidenceBundle, game: str, claim: str
    ) -> ClaimVerificationReport:
        values = {str(item.get("signal")): bool(item.get("value")) for item in bundle.records}
        entity_supported = values.get("claim_entity_match", False)
        role_supported = values.get("role_match", False)
        evidence = [
            EvidenceItem(
                signal="claim_entity_match",
                verdict="supported" if entity_supported else "weakly_supported",
                detail="The claim matches a tracked hero entity."
                if entity_supported
                else "The claim entity is not covered by current evidence.",
                source="rules",
            ),
            EvidenceItem(
                signal="role_match",
                verdict="supported" if role_supported else "partially_supported",
                detail="The claim states an offlane context."
                if role_supported
                else "The claim role is ambiguous or missing.",
                source="rules",
            ),
        ]
        verdict: Verdict = "partially_supported" if entity_supported else "weakly_supported"
        confidence = 0.76 if entity_supported and role_supported else 0.48
        return ClaimVerificationReport(
            report_type="claim_verification",
            game=game,
            claim=claim,
            verdict=verdict,
            evidence=evidence,
            confidence=confidence,
            missing_data=bundle.missing,
        )

    async def _hero_recommendation(self, record: dict[str, Any], role: str) -> HeroRecommendation:
        hero_name = str(
            record.get("hero")
            or record.get("hero_name")
            or record.get("localized_name")
            or "Unknown"
        )
        win_rate = float(record.get("win_rate", 0.5))
        pick_rate = float(record.get("pick_rate", 0.0))
        ban_rate = float(record.get("ban_rate", 0.0))
        pro_presence = float(record.get("pro_presence", 0.0))
        patch_impact_score = float(record.get("patch_impact_score", 0.5))
        trend_score = float(record.get("trend_score", 0.5))
        meta_score = self._meta_score(
            win_rate, pick_rate, pro_presence, patch_impact_score, trend_score
        )
        confidence = self._confidence(
            [win_rate, min(pick_rate * 5, 1), pro_presence, patch_impact_score, trend_score]
        )
        reasons = [str(item) for item in record.get("reasons", [])]
        practice_advice = [str(item) for item in record.get("practice_advice", [])]
        if self.llm_enabled and self.llm:
            try:
                insight = await self._llm_hero_insight(
                    hero_name,
                    role,
                    win_rate,
                    pick_rate,
                    pro_presence,
                    patch_impact_score,
                    meta_score,
                )
                reasons = insight.get("reasons", reasons)[:3]
                practice_advice = insight.get("practice_advice", practice_advice)[:3]
            except Exception as exc:
                logger.warning("Hero insight generation failed for %s: %s", hero_name, exc)
        return HeroRecommendation(
            hero=hero_name,
            role=role,
            win_rate=win_rate,
            pick_rate=pick_rate,
            ban_rate=ban_rate,
            pro_presence=pro_presence,
            meta_score=meta_score,
            confidence=confidence,
            recommendation=self._tier(meta_score),
            reasons=reasons,
            practice_advice=practice_advice,
            evidence=self._hero_evidence(hero_name, win_rate, pro_presence),
        )

    async def _llm_hero_insight(
        self,
        hero_name: str,
        role: str,
        win_rate: float,
        pick_rate: float,
        pro_presence: float,
        patch_impact_score: float,
        meta_score: int,
    ) -> dict[str, list[str]]:
        prompt = render_prompt(
            "analyzer_meta_hero_insights",
            {
                "role": role,
                "hero_name": hero_name,
                "meta_score": meta_score,
                "tier": self._tier(meta_score),
                "win_rate": f"{win_rate:.1%}",
                "pick_rate": f"{pick_rate:.1%}",
                "pro_presence": f"{pro_presence:.1%}",
                "patch_impact_score": f"{patch_impact_score:+.2f}",
            },
        )
        return await self.llm.complete_json(
            [
                {"role": "system", "content": "You are a concise Dota 2 tactical analyst."},
                {"role": "user", "content": prompt},
            ],
            temperature=self.policy.llm.hero_analyzer.temperature,
            max_tokens=self.policy.llm.hero_analyzer.max_tokens,
        )

    def _hero_evidence(
        self, hero_name: str, win_rate: float, pro_presence: float
    ) -> list[EvidenceItem]:
        evidence_policy = self.policy.hero_report.evidence
        return [
            EvidenceItem(
                signal="win_rate",
                verdict=self._threshold_verdict(
                    win_rate,
                    partial=evidence_policy.partial_win_rate,
                    supported=evidence_policy.supported_win_rate,
                ),
                detail=f"{hero_name} sample win rate is {win_rate:.1%}.",
                source="opendota",
            ),
            EvidenceItem(
                signal="pro_presence",
                verdict=self._threshold_verdict(
                    pro_presence,
                    partial=evidence_policy.partial_pro_presence,
                    supported=evidence_policy.supported_pro_presence,
                ),
                detail=f"{hero_name} sample pro presence is {pro_presence:.1%}.",
                source="opendota",
            ),
        ]

    @staticmethod
    def _threshold_verdict(value: float, *, partial: float, supported: float) -> Verdict:
        if value >= supported:
            return "supported"
        if value >= partial:
            return "partially_supported"
        return "weakly_supported"

    def _meta_score(
        self,
        win_rate: float,
        pick_rate: float,
        pro_presence: float,
        patch_impact_score: float,
        trend_score: float,
    ) -> int:
        normalization = self.policy.hero_report.normalization
        weights = self.policy.hero_report.score_weights
        win_score = _normalize(
            win_rate,
            low=normalization.win_rate_low,
            high=normalization.win_rate_high,
        )
        pick_score = _normalize(
            pick_rate,
            low=normalization.pick_rate_low,
            high=normalization.pick_rate_high,
        )
        score = (
            weights.win_rate * win_score
            + weights.pick_rate * pick_score
            + weights.pro_presence * pro_presence
            + weights.patch_impact * patch_impact_score
            + weights.trend * trend_score
        )
        return round(score * 100)

    @staticmethod
    def _confidence(values: list[float]) -> float:
        return round(sum(values) / len(values), 2) if values else 0.0

    def _tier(self, score: int) -> str:
        tiers = self.policy.hero_report.tiers
        if score >= tiers.s:
            return "S"
        if score >= tiers.a:
            return "A"
        if score >= tiers.b:
            return "B"
        return "C"


def _normalize(value: float, *, low: float, high: float) -> float:
    if value <= low:
        return 0.0
    if value >= high:
        return 1.0
    return (value - low) / (high - low)
