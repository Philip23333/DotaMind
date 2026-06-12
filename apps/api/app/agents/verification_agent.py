from app.api.v1.schemas import EvidenceItem, Verdict


class VerificationAgent:
    """Produces evidence labels for claims and report entries."""

    def hero_evidence(
        self,
        hero: str,
        *,
        win_rate: float,
        pro_presence: float,
    ) -> list[EvidenceItem]:
        return [
            EvidenceItem(
                signal="High-MMR win rate",
                verdict=self._verdict_from_threshold(win_rate, partial=0.51, supported=0.525),
                detail=f"{hero} sample win rate is {win_rate:.1%}.",
                source="OpenDota",
            ),
            EvidenceItem(
                signal="Professional draft presence",
                verdict=self._verdict_from_threshold(pro_presence, partial=0.25, supported=0.40),
                detail=f"{hero} sample pro presence is {pro_presence:.1%}.",
                source="STRATZ",
            ),
        ]

    def claim_verdict(self, claim: str) -> tuple[Verdict, list[EvidenceItem], list[str], float]:
        normalized = claim.lower()
        mentions_beastmaster = "beastmaster" in normalized
        mentions_offlane = "offlane" in normalized or "position 3" in normalized

        evidence = [
            EvidenceItem(
                signal="Claim entity match",
                verdict="supported" if mentions_beastmaster else "weakly_supported",
                detail="The MVP fixture contains Beastmaster offlane evidence."
                if mentions_beastmaster
                else "The MVP fixture only covers a small set of offlane heroes.",
                source="MetaMind fixtures",
            ),
            EvidenceItem(
                signal="Role match",
                verdict="supported" if mentions_offlane else "partially_supported",
                detail="The claim targets offlane context."
                if mentions_offlane
                else "The claim does not clearly state a role.",
                source="MetaMind planner",
            ),
        ]
        missing_data = ["Live STRATZ pro draft sample", "Current official patch notes"]
        verdict: Verdict = "partially_supported" if mentions_beastmaster else "weakly_supported"
        confidence = 0.76 if mentions_beastmaster else 0.48
        return verdict, evidence, missing_data, confidence

    @staticmethod
    def _verdict_from_threshold(value: float, *, partial: float, supported: float) -> Verdict:
        if value >= supported:
            return "supported"
        if value >= partial:
            return "partially_supported"
        return "weakly_supported"
