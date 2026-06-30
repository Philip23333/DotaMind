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
from app.domain.evidence import EvidenceBundle, Source
from app.domain.reports import PatchImpactReport, TeamDataFreshness, TeamReport
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
                    "data_freshness": {
                        "latest_match_time": 1_718_000_000,
                        "latest_match_at": "2024-06-09T10:13:20Z",
                        "sample_window_days": 30,
                        "matches_in_window": 5,
                        "match_details_analyzed": 5,
                        "opendota_cache_hits": 2,
                        "opendota_cache_misses": 4,
                    },
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
    assert report.data_freshness.latest_match_at == "2024-06-09T10:13:20Z"
    assert report.data_freshness.opendota_cache_hits == 2


def test_team_report_trace_marks_insufficient_data_quality() -> None:
    service = ReportService()
    service.pipeline.retriever.retrieve_team = AsyncMock(
        return_value=EvidenceBundle(
            task_type="team_report",
            query={"team_name": "Sparse Team"},
            records=[
                {
                    "team_name": "Sparse Team",
                    "recent_record": "1-0 in last 1 matches",
                    "matches_in_window": 1,
                    "match_details_analyzed": 1,
                    "signature_heroes": ["Puck"],
                    "patch_adaptation_score": 50,
                    "recent_win_rate": 1.0,
                    "data_freshness": {
                        "latest_match_time": 1_718_000_000,
                        "latest_match_at": "2024-06-09T10:13:20Z",
                        "sample_window_days": 30,
                        "matches_in_window": 1,
                        "match_details_analyzed": 1,
                        "opendota_cache_hits": 0,
                        "opendota_cache_misses": 1,
                    },
                }
            ],
            sources=["opendota"],
            data_source="opendota",
        )
    )

    trace, _report = asyncio.run(
        service.pipeline.run(mappers.team_request(TeamReportRequest(team_name="Sparse Team")))
    )

    critic_task = next(task for task in trace if task.agent == "critic")
    assert critic_task.status == "failed"
    assert "insufficient match sample" in critic_task.action
    assert "limited detail sample" not in critic_task.action


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
    critic_task = next(task for task in result.tasks if task.agent == "critic")
    assert critic_task.action == "quality gate passed"
    assert critic_task.status == "completed"


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
    assert review.severity == "failed"
    assert review.reasons
    assert review.metadata["evidence_count"] == 0


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
    assert review.severity == "pass"
    assert review.reasons == []
    assert review.metadata["evidence_count"] == 1


def test_critic_fails_patch_mock_data() -> None:
    report = PatchImpactReport(
        report_type="patch_impact",
        game="dota2",
        patch="unknown",
        summary="Patch data unavailable.",
        winners=[],
        losers=[],
        item_impacts=[],
        lineup_trends=[],
        practice_advice=[],
        sources=[Source("MetaMind Fixtures", "fixture", None, "mocked")],
        confidence=0.4,
    )
    bundle = EvidenceBundle(
        task_type="patch_impact",
        query={"patch": "unknown"},
        sources=["mock"],
        data_source="mock",
        missing=["structured patch JSON"],
    )

    review = CriticAgent().review_report(report, bundle)

    assert review.passed is False
    assert review.severity == "failed"
    assert any("uses mock data" in reason for reason in review.reasons)
    assert review.metadata["data_source"] == "mock"


def test_critic_warns_meta_mock_data() -> None:
    report = asyncio.run(
        ReportService().run(mappers.meta_request(MetaReportRequest(role="offlane")))
    )
    mocked_report = report.__class__(
        **{**report.__dict__, "sources": [Source("MetaMind Fixtures", "fixture", None, "mocked")]}
    )
    bundle = EvidenceBundle(
        task_type="meta_report",
        query={"role": "offlane"},
        records=[],
        sources=["mock"],
        data_source="mock",
        missing=["live OpenDota hero stats"],
    )

    review = CriticAgent().review_report(mocked_report, bundle)

    assert review.passed is True
    assert review.severity == "warning"
    assert any("uses mock data" in reason for reason in review.reasons)


def test_critic_checks_team_freshness_sample_and_confidence() -> None:
    report = TeamReport(
        report_type="team_report",
        game="dota2",
        team_name="Old Team",
        time_range="last_30_days",
        summary="Old Team report is based on sparse data.",
        recent_record="1-1 in last 2 matches",
        matches_in_window=2,
        match_details_analyzed=2,
        data_freshness=TeamDataFreshness(
            latest_match_time=1_609_459_200,
            latest_match_at="2021-01-01T00:00:00Z",
            sample_window_days=30,
            matches_in_window=2,
            match_details_analyzed=2,
            opendota_cache_hits=0,
            opendota_cache_misses=3,
        ),
        signature_heroes=[],
        draft_preferences=[],
        win_patterns=[],
        loss_patterns=[],
        patch_adaptation_score=10,
        key_players=[],
        sources=[Source("OpenDota", "public_api", "https://docs.opendota.com/", "live")],
        confidence=0.34,
    )

    review = CriticAgent().review_report(
        report,
        EvidenceBundle(
            task_type="team_report",
            query={"team_name": "Old Team"},
            sources=["opendota"],
            data_source="opendota",
        ),
    )

    assert review.passed is False
    assert review.severity == "failed"
    assert any("Latest team match" in reason for reason in review.reasons)
    assert any("insufficient match sample" in reason for reason in review.reasons)
    assert any("confidence" in reason for reason in review.reasons)
