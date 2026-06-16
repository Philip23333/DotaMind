import asyncio

from app.agents.critic import CriticAgent
from app.agents.orchestrator import OrchestratorAgent
from app.api.v1.schemas import (
    ClaimVerificationRequest,
    EvidenceItem,
    MetaReportRequest,
    NaturalLanguageQueryRequest,
    PatchImpactRequest,
    TeamReportRequest,
)
from app.services.claim_verification_service import ClaimVerificationService
from app.services.meta_report_service import MetaReportService
from app.services.patch_impact_service import PatchImpactService
from app.services.team_report_service import TeamReportService


def test_meta_report_ranks_offlane_heroes() -> None:
    report = asyncio.run(MetaReportService().get_report(MetaReportRequest(role="offlane")))

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
    report = asyncio.run(
        TeamReportService().get_report(TeamReportRequest(team_name="Team Spirit"))
    )

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


def test_orchestrator_routes_patch_query_to_v21_tasks() -> None:
    plan = OrchestratorAgent().plan(
        NaturalLanguageQueryRequest(query="What changed in patch 7.41d?")
    )

    assert plan.service == "patch_impact"
    assert plan.tasks[0].agent == "orchestrator"
    assert any(task.agent == "critic" for task in plan.tasks)


def test_critic_rejects_missing_evidence() -> None:
    review = CriticAgent().review_evidence([])

    assert review.passed is False
    assert review.reasons


def test_critic_passes_supported_evidence() -> None:
    review = CriticAgent().review_evidence(
        [
            EvidenceItem(
                signal="High-MMR win rate",
                verdict="supported",
                detail="Sample win rate is above threshold.",
                source="OpenDota",
            )
        ]
    )

    assert review.passed is True
    assert review.reasons == []
