import logging
import time
from typing import Any, Literal

from app.api.v1.schemas import EvidenceItem, HeroRecommendation, Verdict
from app.core.config import get_settings
from app.llm.provider import get_llm_provider

logger = logging.getLogger(__name__)

TaskType = Literal["meta_report", "patch_impact", "team_report", "claim_verification"]


class AnalyzerAgent:
    """Single analysis boundary with optional LLM-backed insights."""

    def __init__(self, use_llm: bool = True):
        self.use_llm = use_llm
        settings = get_settings()
        self.llm_enabled = settings.llm_enabled and use_llm
        logger.info(
            "Analyzer init use_llm=%s settings_llm_enabled=%s effective_llm_enabled=%s model=%s",
            use_llm,
            settings.llm_enabled,
            self.llm_enabled,
            settings.llm_model,
        )
        if self.llm_enabled:
            try:
                self.llm = get_llm_provider()
                logger.info("Analyzer LLM provider ready model=%s", settings.llm_model)
            except Exception as e:
                logger.warning(f"Failed to initialize LLM provider: {e}")
                self.llm_enabled = False

    def confidence_bucket(self, confidence: float) -> Literal["high", "medium", "low", "none"]:
        if confidence >= 0.75:
            return "high"
        if confidence >= 0.5:
            return "medium"
        if confidence > 0:
            return "low"
        return "none"

    def weakest_verdict(self, evidence: list[EvidenceItem]) -> Verdict:
        order: dict[Verdict, int] = {
            "unsupported": 0,
            "weakly_supported": 1,
            "partially_supported": 2,
            "supported": 3,
        }
        if not evidence:
            return "unsupported"
        return min((item.verdict for item in evidence), key=lambda verdict: order[verdict])

    async def analyze_meta_report(
        self, records: list[dict[str, Any]], role: str
    ) -> list[HeroRecommendation]:
        """
        Analyze meta report with optional LLM insights.
        
        Computes meta_score using weighted formula, generates evidence,
        and optionally uses LLM to generate reasons and practice advice.
        """
        recommendations = []
        logger.info(
            "Analyzer meta_report start role=%s records=%s llm_enabled=%s",
            role,
            len(records),
            self.llm_enabled,
        )
        
        for hero_data in records[:10]:  # Top 10
            win_rate = float(hero_data.get("win_rate", 0.5))
            pick_rate = float(hero_data.get("pick_rate", 0.0))
            ban_rate = float(hero_data.get("ban_rate", 0.0))
            pro_presence = float(hero_data.get("pro_presence", 0.0))
            patch_impact_score = float(hero_data.get("patch_impact_score", 0.0))
            trend_score = float(hero_data.get("trend_score", 0.5))
            hero_name = (
                hero_data.get("hero")
                or hero_data.get("hero_name")
                or hero_data.get("localized_name", "Unknown")
            )
            
            # Weighted formula from ReasoningAgent
            meta_score = int(
                win_rate * 30
                + min(pick_rate * 5, 1) * 25
                + pro_presence * 20
                + (patch_impact_score + 1) / 2 * 15
                + trend_score * 10
            )
            
            # Confidence calculation
            confidence = sum([
                win_rate,
                min(pick_rate * 5, 1),
                pro_presence,
                (patch_impact_score + 1) / 2,
                trend_score
            ]) / 5
            
            # Generate evidence items
            evidence = self._generate_hero_evidence(hero_name, win_rate, pro_presence)
            logger.info(
                "Analyzer hero scored hero=%s role=%s meta_score=%s confidence=%.3f "
                "evidence_items=%s llm_enabled=%s",
                hero_name,
                role,
                meta_score,
                confidence,
                len(evidence),
                self.llm_enabled,
            )
            
            # Generate LLM insights if enabled
            reasons = []
            practice_advice = []
            
            if self.llm_enabled:
                try:
                    insights = await self._generate_hero_insights(
                        hero_name=hero_name,
                        role=role,
                        win_rate=win_rate,
                        pick_rate=pick_rate,
                        pro_presence=pro_presence,
                        patch_impact_score=patch_impact_score,
                        meta_score=meta_score,
                        tier=self._tier_label(meta_score),
                    )
                    reasons = insights.get("reasons", [])
                    practice_advice = insights.get("practice_advice", [])
                    logger.info(
                        "Analyzer LLM insights attached hero=%s reasons=%s practice_advice=%s",
                        hero_name,
                        len(reasons),
                        len(practice_advice),
                    )
                except Exception as e:
                    logger.warning(f"LLM insights generation failed for {hero_name}: {e}")
            
            recommendations.append(
                HeroRecommendation(
                    hero=hero_name,
                    role=role,
                    win_rate=win_rate,
                    pick_rate=pick_rate,
                    ban_rate=ban_rate,
                    pro_presence=pro_presence,
                    meta_score=meta_score,
                    confidence=confidence,
                    recommendation=self._tier_label(meta_score),
                    reasons=reasons,
                    practice_advice=practice_advice,
                    evidence=evidence,
                )
            )
        
        logger.info(
            "Analyzer meta_report complete role=%s recommendations=%s llm_enabled=%s",
            role,
            len(recommendations),
            self.llm_enabled,
        )
        return recommendations

    def _generate_hero_evidence(
        self, hero_name: str, win_rate: float, pro_presence: float
    ) -> list[EvidenceItem]:
        """Generate evidence items based on rule thresholds."""
        evidence = []
        
        # Win rate signal
        if win_rate >= 0.525:
            evidence.append(
                EvidenceItem(
                    signal="high_win_rate",
                    verdict="supported",
                    detail=f"{hero_name} has {win_rate:.1%} win rate (≥52.5%)",
                    source="opendota",
                )
            )
        elif win_rate >= 0.51:
            evidence.append(
                EvidenceItem(
                    signal="partial_win_rate",
                    verdict="partially_supported",
                    detail=f"{hero_name} has {win_rate:.1%} win rate (≥51%)",
                    source="opendota",
                )
            )
        else:
            evidence.append(
                EvidenceItem(
                    signal="low_win_rate",
                    verdict="weakly_supported",
                    detail=f"{hero_name} has {win_rate:.1%} win rate (<51%)",
                    source="opendota",
                )
            )
        
        # Pro presence signal
        if pro_presence >= 0.4:
            evidence.append(
                EvidenceItem(
                    signal="high_pro_presence",
                    verdict="supported",
                    detail=f"{hero_name} has {pro_presence:.1%} pro presence (≥40%)",
                    source="opendota",
                )
            )
        elif pro_presence >= 0.25:
            evidence.append(
                EvidenceItem(
                    signal="partial_pro_presence",
                    verdict="partially_supported",
                    detail=f"{hero_name} has {pro_presence:.1%} pro presence (≥25%)",
                    source="opendota",
                )
            )
        else:
            evidence.append(
                EvidenceItem(
                    signal="low_pro_presence",
                    verdict="weakly_supported",
                    detail=f"{hero_name} has {pro_presence:.1%} pro presence (<25%)",
                    source="opendota",
                )
            )
        
        return evidence

    async def _generate_hero_insights(
        self,
        hero_name: str,
        role: str,
        win_rate: float,
        pick_rate: float,
        pro_presence: float,
        patch_impact_score: float,
        meta_score: int,
        tier: str,
    ) -> dict[str, list[str]]:
        """
        Use LLM to generate reasons and practice advice for a hero.
        
        Returns:
            {"reasons": [...], "practice_advice": [...]}
        """
        started_at = time.perf_counter()
        logger.info(
            "Analyzer LLM insight request start hero=%s role=%s tier=%s "
            "meta_score=%s max_tokens=%s",
            hero_name,
            role,
            tier,
            meta_score,
            800,
        )
        prompt = f"""You are analyzing Dota 2 hero recommendations for the {role} position.

Hero: {hero_name}
Meta Score: {meta_score}/100 (Tier {tier})
Win Rate: {win_rate:.1%}
Pick Rate: {pick_rate:.1%}
Pro Presence: {pro_presence:.1%}
Patch Impact: {patch_impact_score:+.2f}

Generate a JSON response with:
1. "reasons": 2-3 short reasons WHY this hero is good/bad for {role} (each reason 10-15 words max)
2. "practice_advice": 2-3 actionable tips for playing this hero (each tip 10-15 words max)

Keep language concise and tactical. Focus on the current meta and patch.

Example format:
{{
  "reasons": [
    "High win rate shows strong performance in current patch",
    "Popular in pro scene with proven strategies"
  ],
  "practice_advice": [
    "Focus on farming efficiency in early game",
    "Coordinate with team for power spike timing"
  ]
}}"""

        messages = [
            {
                "role": "system",
                "content": "You are a Dota 2 expert analyst providing concise, tactical insights.",
            },
            {"role": "user", "content": prompt}
        ]
        
        try:
            response = await self.llm.complete_json(messages, temperature=0.2, max_tokens=800)
            result = {
                "reasons": response.get("reasons", [])[:3],
                "practice_advice": response.get("practice_advice", [])[:3],
            }
            logger.info(
                "Analyzer LLM insight request success hero=%s elapsed_ms=%s "
                "reasons=%s practice_advice=%s",
                hero_name,
                round((time.perf_counter() - started_at) * 1000),
                len(result["reasons"]),
                len(result["practice_advice"]),
            )
            return result
        except Exception as e:
            logger.error(
                "Analyzer LLM insight request failed hero=%s elapsed_ms=%s error=%s",
                hero_name,
                round((time.perf_counter() - started_at) * 1000),
                e,
            )
            return {"reasons": [], "practice_advice": []}

    def _tier_label(self, meta_score: int) -> str:
        """Convert meta_score to tier label."""
        if meta_score >= 75:
            return "S"
        if meta_score >= 65:
            return "A"
        if meta_score >= 55:
            return "B"
        if meta_score >= 45:
            return "C"
        return "D"
