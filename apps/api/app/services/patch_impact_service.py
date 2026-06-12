from app.agents.data_agent import DataAgent
from app.agents.patch_agent import PatchAgent
from app.api.v1.schemas import PatchImpactRequest, PatchImpactResponse


class PatchImpactService:
    def __init__(self) -> None:
        self.data_agent = DataAgent()
        self.patch_agent = PatchAgent()

    def get_report(self, request: PatchImpactRequest) -> PatchImpactResponse:
        patch = self.patch_agent.summarize_patch(request.patch)
        role_note = f" Focused on {request.role} impact." if request.role else ""

        return PatchImpactResponse(
            game=request.game,
            patch=str(patch["patch"]),
            summary=f"{patch['summary']}{role_note}",
            winners=[str(item) for item in patch["winners"]],
            losers=[str(item) for item in patch["losers"]],
            item_impacts=[str(item) for item in patch["item_impacts"]],
            lineup_trends=[str(item) for item in patch["lineup_trends"]],
            practice_advice=[str(item) for item in patch["practice_advice"]],
            sources=self.data_agent.sources(),
            confidence=0.68,
        )
