from app.agents.data_agent import DataAgent
from app.api.v1.schemas import TeamReportRequest, TeamReportResponse
from app.data.mock_data import MOCK_TEAM_REPORT


class TeamReportService:
    def __init__(self) -> None:
        self.data_agent = DataAgent()

    def get_report(self, request: TeamReportRequest) -> TeamReportResponse:
        return TeamReportResponse(
            game=request.game,
            team_name=request.team_name or str(MOCK_TEAM_REPORT["team_name"]),
            time_range=request.time_range,
            summary=str(MOCK_TEAM_REPORT["summary"]),
            recent_record=str(MOCK_TEAM_REPORT["recent_record"]),
            signature_heroes=[str(item) for item in MOCK_TEAM_REPORT["signature_heroes"]],
            draft_preferences=[str(item) for item in MOCK_TEAM_REPORT["draft_preferences"]],
            win_patterns=[str(item) for item in MOCK_TEAM_REPORT["win_patterns"]],
            loss_patterns=[str(item) for item in MOCK_TEAM_REPORT["loss_patterns"]],
            patch_adaptation_score=int(MOCK_TEAM_REPORT["patch_adaptation_score"]),
            key_players=[str(item) for item in MOCK_TEAM_REPORT["key_players"]],
            sources=self.data_agent.sources(),
            confidence=0.72,
        )
