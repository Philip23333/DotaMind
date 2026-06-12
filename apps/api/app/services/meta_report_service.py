from app.agents.data_agent import DataAgent
from app.agents.reasoning_agent import MetaReasoningAgent
from app.agents.report_agent import ReportAgent
from app.agents.verification_agent import VerificationAgent
from app.api.v1.schemas import HeroRecommendation, MetaReportRequest, MetaReportResponse


class MetaReportService:
    def __init__(self) -> None:
        self.data_agent = DataAgent()
        self.reasoning_agent = MetaReasoningAgent()
        self.verification_agent = VerificationAgent()
        self.report_agent = ReportAgent()

    def get_report(self, request: MetaReportRequest) -> MetaReportResponse:
        hero_rows = self.data_agent.hero_stats_for_role(request.role)
        heroes = [self._to_recommendation(hero) for hero in hero_rows]
        heroes.sort(key=lambda hero: hero.meta_score, reverse=True)

        confidence = self.reasoning_agent.confidence([hero.confidence for hero in heroes])

        return MetaReportResponse(
            game=request.game,
            patch=request.patch,
            role=request.role,
            summary=self.report_agent.meta_summary(request.role, len(heroes)),
            top_heroes=heroes,
            sources=self.data_agent.sources(),
            analysis_steps=self.report_agent.analysis_steps(),
            confidence=confidence,
        )

    def _to_recommendation(self, row: dict[str, object]) -> HeroRecommendation:
        win_rate = float(row["win_rate"])
        pick_rate = float(row["pick_rate"])
        pro_presence = float(row["pro_presence"])
        patch_impact_score = float(row["patch_impact_score"])
        trend_score = float(row["trend_score"])

        meta_score = self.reasoning_agent.meta_score(
            win_rate=win_rate,
            pick_rate=pick_rate,
            pro_presence=pro_presence,
            patch_impact_score=patch_impact_score,
            trend_score=trend_score,
        )
        confidence = self.reasoning_agent.confidence(
            [win_rate, min(pick_rate * 5, 1), pro_presence, patch_impact_score, trend_score]
        )

        return HeroRecommendation(
            hero=str(row["hero"]),
            role=str(row["role"]),
            win_rate=win_rate,
            pick_rate=pick_rate,
            ban_rate=float(row["ban_rate"]),
            pro_presence=pro_presence,
            meta_score=meta_score,
            confidence=confidence,
            recommendation=str(row["recommendation"]),
            reasons=[str(reason) for reason in row["reasons"]],
            practice_advice=[str(advice) for advice in row["practice_advice"]],
            evidence=self.verification_agent.hero_evidence(
                str(row["hero"]), win_rate=win_rate, pro_presence=pro_presence
            ),
        )
