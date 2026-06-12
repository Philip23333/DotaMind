from app.api.v1.schemas import (
    ClaimVerificationRequest,
    MetaReportRequest,
    PatchImpactRequest,
    TeamReportRequest,
)
from app.services.claim_verification_service import ClaimVerificationService
from app.services.meta_report_service import MetaReportService
from app.services.patch_impact_service import PatchImpactService
from app.services.team_report_service import TeamReportService


def test_meta_report_ranks_offlane_heroes() -> None:
    report = MetaReportService().get_report(MetaReportRequest(role="offlane"))

    assert report.report_type == "meta_report"
    assert report.top_heroes
    assert report.top_heroes[0].meta_score >= report.top_heroes[-1].meta_score
    assert report.sources


def test_patch_impact_returns_winners_and_losers() -> None:
    report = PatchImpactService().get_report(PatchImpactRequest(patch="latest"))

    assert report.winners
    assert report.losers
    assert report.confidence > 0


def test_team_report_contains_patch_adaptation_score() -> None:
    report = TeamReportService().get_report(TeamReportRequest(team_name="Team Spirit"))

    assert report.patch_adaptation_score > 0
    assert report.signature_heroes


def test_claim_verification_marks_beastmaster_claim_partial() -> None:
    report = ClaimVerificationService().verify(
        ClaimVerificationRequest(
            claim="Beastmaster is one of the strongest offlaners in current patch."
        )
    )

    assert report.verdict == "partially_supported"
    assert report.evidence
