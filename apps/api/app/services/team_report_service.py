import logging

from app.agents.data_agent import DataAgent
from app.api.v1.schemas import TeamReportRequest, TeamReportResponse
from app.core.config import get_settings
from app.data.mock_data import MOCK_TEAM_REPORT
from app.integrations.opendota import OpenDotaClient

logger = logging.getLogger(__name__)


class TeamReportService:
    def __init__(self) -> None:
        self.data_agent = DataAgent()
        settings = get_settings()
        self._opendota = OpenDotaClient(settings.opendota_base_url)

    async def get_report(self, request: TeamReportRequest) -> TeamReportResponse:
        """
        Fetch real team data from OpenDota. Falls back to mock if API fails
        or team is not found.
        """
        try:
            data = await self._opendota.get_team_report_data(
                request.team_name, match_limit=30
            )
            if data is not None:
                logger.info(
                    "OpenDota team report for '%s': %s",
                    request.team_name,
                    data["recent_record"],
                )
                return self._build_response(request, data, source="opendota")
        except Exception as exc:
            logger.warning("Team report fetch failed (%s), using mock", exc)

        return self._build_mock_response(request)

    def _build_response(
        self, request: TeamReportRequest, data: dict, source: str
    ) -> TeamReportResponse:
        wr = data["recent_win_rate"]
        summary = (
            f"{data['team_name']} has a {data['recent_record']} record. "
            f"Hero pool depth: {data['hero_pool_depth']} heroes. "
            f"Signature picks include {', '.join(data['signature_heroes'][:3])}."
        )

        draft_prefs = [
            f"Top picks: {', '.join(data['signature_heroes'][:5])}.",
            f"Hero pool depth: {data['hero_pool_depth']} heroes with 30+ games.",
            f"Draft flexibility score: {data['draft_flexibility']:.0%}.",
        ]

        return TeamReportResponse(
            game=request.game,
            team_name=data["team_name"],
            time_range=request.time_range,
            summary=summary,
            recent_record=data["recent_record"],
            signature_heroes=data["signature_heroes"],
            draft_preferences=draft_prefs,
            win_patterns=data["win_patterns"] or ["No clear pattern identified."],
            loss_patterns=data["loss_patterns"] or ["No clear pattern identified."],
            patch_adaptation_score=data["patch_adaptation_score"],
            key_players=data["key_players"] or data["signature_heroes"][:3],
            sources=self.data_agent.sources(source),
            confidence=round(min(0.85, 0.5 + wr * 0.3 + data["draft_flexibility"] * 0.2), 2),
        )

    def _build_mock_response(self, request: TeamReportRequest) -> TeamReportResponse:
        return TeamReportResponse(
            game=request.game,
            team_name=request.team_name or str(MOCK_TEAM_REPORT["team_name"]),
            time_range=request.time_range,
            summary=str(MOCK_TEAM_REPORT["summary"]),
            recent_record=str(MOCK_TEAM_REPORT["recent_record"]),
            signature_heroes=[str(i) for i in MOCK_TEAM_REPORT["signature_heroes"]],
            draft_preferences=[str(i) for i in MOCK_TEAM_REPORT["draft_preferences"]],
            win_patterns=[str(i) for i in MOCK_TEAM_REPORT["win_patterns"]],
            loss_patterns=[str(i) for i in MOCK_TEAM_REPORT["loss_patterns"]],
            patch_adaptation_score=int(MOCK_TEAM_REPORT["patch_adaptation_score"]),
            key_players=[str(i) for i in MOCK_TEAM_REPORT["key_players"]],
            sources=self.data_agent.sources("mock"),
            confidence=0.40,
        )
