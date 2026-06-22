import asyncio
from unittest.mock import AsyncMock

from app.api.v1 import mappers
from app.api.v1.schemas import (
    ClaimVerificationRequest,
    EvidenceItem,
    MetaReportRequest,
    NaturalLanguageQueryRequest,
    PatchImpactRequest,
    TeamReportRequest,
)
from app.application.query_service import QueryService
from app.application.report_service import ReportService
from app.domain.evidence import EvidenceBundle
from app.domain.teams import TeamSelection
from app.pipeline.critic import CriticAgent
from app.pipeline.orchestrator import OrchestratorAgent


def test_meta_report_ranks_offlane_heroes() -> None:
    report = asyncio.run(
        ReportService().run(mappers.meta_request(MetaReportRequest(role="offlane")))
    )

    assert report.report_type == "meta_report"
    assert report.top_heroes
    assert report.top_heroes[0].meta_score >= report.top_heroes[-1].meta_score
    assert report.sources


def test_patch_impact_returns_winners_and_losers() -> None:
    report = asyncio.run(
        ReportService().run(mappers.patch_request(PatchImpactRequest(patch="latest")))
    )

    assert report.winners
    assert report.losers
    assert report.confidence > 0


def test_team_report_contains_patch_adaptation_score() -> None:
    service = ReportService()
    service.pipeline.retriever.retrieve_team = AsyncMock(
        return_value=EvidenceBundle(
            task_type="team_report",
            query={"team_name": "Team Spirit"},
            records=[
                {
                    "team_name": "Team Spirit",
                    "recent_record": "3-2 in last 5 matches",
                    "signature_heroes": ["Puck", "Mars"],
                    "patch_adaptation_score": 70,
                    "recent_win_rate": 0.6,
                }
            ],
            sources=["opendota"],
            data_source="opendota",
        )
    )

    report = asyncio.run(
        service.run(mappers.team_request(TeamReportRequest(team_name="Team Spirit")))
    )

    assert report.patch_adaptation_score > 0
    assert report.signature_heroes


def test_claim_verification_marks_beastmaster_claim_partial() -> None:
    report = asyncio.run(
        ReportService().run(
            mappers.claim_request(
                ClaimVerificationRequest(
                    claim="Beastmaster is one of the strongest offlaners in current patch."
                )
            )
        )
    )

    assert report.verdict == "partially_supported"
    assert report.evidence


def test_orchestrator_routes_patch_query_to_v21_tasks() -> None:
    plan = asyncio.run(
        OrchestratorAgent().plan_query(
            NaturalLanguageQueryRequest(query="What changed in patch 7.41d?").query
        )
    )

    assert plan.task_type == "patch_impact"
    assert plan.trace[0].agent == "orchestrator"


def test_query_service_returns_trace_with_critic() -> None:
    result = asyncio.run(QueryService().run("What changed in patch 7.41d?"))

    assert result.routed_service == "patch_impact"
    assert any(task.agent == "critic" for task in result.tasks)


def test_query_service_bypasses_llm_for_explicit_team_selection() -> None:
    service = QueryService()
    service.orchestrator.plan_query = AsyncMock(
        side_effect=AssertionError("LLM planning must not run for an explicit selection")
    )
    service.pipeline.run = AsyncMock(return_value=([], object()))

    result = asyncio.run(
        service.run(
            "How Team BB play lately?",
            team_selection=TeamSelection(
                team_id=8255888,
                team_name="BB",
                time_range="last_7_days",
            ),
        )
    )

    request = service.pipeline.run.await_args.args[0]
    assert result.routed_service == "team_report"
    assert request.team_id == 8255888
    assert request.team_name == "BB"
    assert request.time_range == "last_7_days"
    service.orchestrator.plan_query.assert_not_awaited()


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
