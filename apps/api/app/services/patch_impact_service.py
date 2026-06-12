from app.agents.data_agent import DataAgent
from app.agents.patch_agent import PatchAgent
from app.api.v1.schemas import PatchImpactRequest, PatchImpactResponse
from app.integrations.patch_notes import load_patch


class PatchImpactService:
    def __init__(self) -> None:
        self.data_agent = DataAgent()
        self.patch_agent = PatchAgent()

    def get_report(self, request: PatchImpactRequest) -> PatchImpactResponse:
        patch = self.patch_agent.summarize_patch(request.patch)
        role_note = f" Focused on {request.role} impact." if request.role else ""

        # Confidence: high if reading real patch JSON, lower if mock
        patch_data = load_patch(request.patch)
        if patch_data is not None:
            data_source = "opendota"
            # More changes in JSON = more confidence
            n_changes = len(patch_data.get("changes", []))
            confidence = min(0.90, 0.60 + n_changes * 0.002)
        else:
            data_source = "mock"
            confidence = 0.40

        return PatchImpactResponse(
            game=request.game,
            patch=str(patch["patch"]),
            summary=f"{patch['summary']}{role_note}",
            winners=[str(item) for item in patch["winners"]],
            losers=[str(item) for item in patch["losers"]],
            item_impacts=[str(item) for item in patch["item_impacts"]],
            lineup_trends=[str(item) for item in patch["lineup_trends"]],
            practice_advice=[str(item) for item in patch["practice_advice"]],
            sources=self.data_agent.sources(data_source),
            confidence=round(confidence, 2),
        )
