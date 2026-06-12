from app.agents.verification_agent import VerificationAgent
from app.api.v1.schemas import ClaimVerificationRequest, ClaimVerificationResponse


class ClaimVerificationService:
    def __init__(self) -> None:
        self.verification_agent = VerificationAgent()

    def verify(self, request: ClaimVerificationRequest) -> ClaimVerificationResponse:
        verdict, evidence, missing_data, confidence = self.verification_agent.claim_verdict(
            request.claim
        )
        return ClaimVerificationResponse(
            game=request.game,
            claim=request.claim,
            verdict=verdict,
            evidence=evidence,
            confidence=confidence,
            missing_data=missing_data,
        )
