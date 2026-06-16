from typing import Any, Literal

from app.api.v1.schemas import EvidenceItem, HeroRecommendation, Verdict

TaskType = Literal["meta_report", "patch_impact", "team_report", "claim_verification"]


class AnalyzerAgent:
    """Single analysis boundary for future LLM-backed claim generation."""

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

    def analyze_meta_report(
        self, records: list[dict[str, Any]], role: str
    ) -> list[HeroRecommendation]:
        """
        Rule-based analysis for meta report (Milestone 1 - no LLM).
        
        Computes meta_score using weighted formula and generates evidence.
        """
        recommendations = []
        
        for hero_data in records[:10]:  # Top 10
            win_rate = float(hero_data.get("win_rate", 0.5))
            pick_rate = float(hero_data.get("pick_rate", 0.0))
            ban_rate = float(hero_data.get("ban_rate", 0.0))
            pro_presence = float(hero_data.get("pro_presence", 0.0))
            patch_impact_score = float(hero_data.get("patch_impact_score", 0.0))
            trend_score = float(hero_data.get("trend_score", 0.5))
            
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
            evidence = self._generate_hero_evidence(
                hero_data.get("hero") or hero_data.get("hero_name") or hero_data.get("localized_name", "Unknown"),
                win_rate,
                pro_presence
            )
            
            recommendations.append(
                HeroRecommendation(
                    hero=hero_data.get("hero") or hero_data.get("hero_name") or hero_data.get("localized_name", "Unknown"),
                    role=role,
                    win_rate=win_rate,
                    pick_rate=pick_rate,
                    ban_rate=ban_rate,
                    pro_presence=pro_presence,
                    meta_score=meta_score,
                    confidence=confidence,
                    recommendation=self._tier_label(meta_score),
                    reasons=[],  # LLM will fill this in Milestone 2
                    practice_advice=[],  # LLM will fill this in Milestone 2
                    evidence=evidence,
                )
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
