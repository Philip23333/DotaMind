"""
Tests for v2.1 experimental architecture.

Milestone 1: rule-based flow without LLM.
"""

import asyncio

import pytest

from app.api.v1.schemas import EvidenceItem, NaturalLanguageQueryRequest
from app.services.experimental_service import ExperimentalService


def test_experimental_meta_report_flow():
    """
    Test v2.1 flow: Orchestrator → Retriever → Analyzer → Critic → Formatter
    """
    service = ExperimentalService()
    
    request = NaturalLanguageQueryRequest(
        query="What are the best offlane heroes?",
        game="dota2"
    )
    
    routed_service, analysis_steps, result = asyncio.run(service.handle_query(request))
    
    # Verify orchestrator routed correctly
    assert routed_service == "meta_report"
    
    # Verify analysis steps trace
    assert len(analysis_steps) >= 3
    assert any("Orchestrator" in step for step in analysis_steps)
    assert any("Retriever" in step for step in analysis_steps)
    assert any("Analyzer" in step for step in analysis_steps)
    assert any("Critic" in step for step in analysis_steps)
    
    # Verify response structure
    assert result.report_type == "meta_report"
    assert result.role == "offlane"
    assert len(result.top_heroes) > 0
    
    # Verify each hero has evidence
    for hero in result.top_heroes:
        assert len(hero.evidence) > 0
        assert hero.meta_score >= 0
        assert 0 <= hero.confidence <= 1
        
        # Check evidence has required fields
        for evidence in hero.evidence:
            assert evidence.signal
            assert evidence.verdict in ["supported", "partially_supported", "weakly_supported", "unsupported"]
            assert evidence.detail
            assert evidence.source


def test_experimental_team_query_routes_correctly():
    """Test that team-related queries route to team_report."""
    service = ExperimentalService()
    
    request = NaturalLanguageQueryRequest(
        query="How is Team Spirit performing?",
        game="dota2"
    )
    
    # Should route to team_report but not implemented yet
    with pytest.raises(NotImplementedError):
        asyncio.run(service.handle_query(request))


def test_experimental_patch_query_routes_correctly():
    """Test that patch-related queries route to patch_impact."""
    service = ExperimentalService()
    
    request = NaturalLanguageQueryRequest(
        query="What changed in patch 7.41d?",
        game="dota2"
    )
    
    # Should route to patch_impact but not implemented yet
    with pytest.raises(NotImplementedError):
        asyncio.run(service.handle_query(request))


def test_retriever_fetches_real_data():
    """Test that RetrieverTool connects to real data sources."""
    from app.tools.retriever import RetrieverTool
    
    retriever = RetrieverTool()
    
    # Test meta retrieval
    bundle = asyncio.run(retriever.retrieve_meta("offlane", "latest"))
    
    assert bundle.task_type == "meta_report"
    assert bundle.query["role"] == "offlane"
    
    # Should have real data (unless OpenDota is down)
    if bundle.data_source in ["opendota", "mixed"]:
        assert len(bundle.records) > 0
        assert "opendota" in bundle.sources
        
        # Verify hero data structure
        hero = bundle.records[0]
        assert "win_rate" in hero or "localized_name" in hero


def test_analyzer_generates_evidence():
    """Test that AnalyzerAgent generates evidence with correct verdicts."""
    from app.agents.analyzer import AnalyzerAgent
    
    analyzer = AnalyzerAgent()
    
    # Mock hero data
    mock_heroes = [
        {
            "hero_name": "Mars",
            "localized_name": "Mars",
            "win_rate": 0.53,
            "pick_rate": 0.15,
            "ban_rate": 0.10,
            "pro_presence": 0.45,
            "patch_impact_score": 0.3,
            "trend_score": 0.6,
        },
        {
            "hero_name": "Bristleback",
            "localized_name": "Bristleback",
            "win_rate": 0.48,
            "pick_rate": 0.12,
            "ban_rate": 0.05,
            "pro_presence": 0.20,
            "patch_impact_score": -0.15,
            "trend_score": 0.4,
        }
    ]
    
    recommendations = analyzer.analyze_meta_report(mock_heroes, "offlane")
    
    assert len(recommendations) == 2
    
    # Check Mars (high win rate + high pro presence)
    mars = recommendations[0]
    assert mars.hero == "Mars"
    assert len(mars.evidence) >= 2
    
    # Should have supported win_rate evidence
    win_rate_evidence = [e for e in mars.evidence if "win_rate" in e.signal]
    assert len(win_rate_evidence) > 0
    assert win_rate_evidence[0].verdict == "supported"
    
    # Should have supported pro_presence evidence
    pro_evidence = [e for e in mars.evidence if "pro_presence" in e.signal]
    assert len(pro_evidence) > 0
    assert pro_evidence[0].verdict == "supported"


def test_critic_validates_evidence():
    """Test that CriticAgent validates evidence correctly."""
    from app.agents.critic import CriticAgent
    
    critic = CriticAgent()
    
    # Test with good evidence
    good_evidence = [
        EvidenceItem(
            signal="high_win_rate",
            verdict="supported",
            detail="Hero has 53% win rate",
            source="opendota"
        ),
        EvidenceItem(
            signal="high_pro_presence",
            verdict="supported",
            detail="Hero has 45% pro presence",
            source="opendota"
        )
    ]
    
    review = critic.review_evidence(good_evidence)
    assert review.passed is True
    assert len(review.reasons) == 0
    
    # Test with unsupported evidence
    bad_evidence = [
        EvidenceItem(
            signal="some_signal",
            verdict="unsupported",
            detail="No data available",
            source="mock"
        )
    ]
    
    review = critic.review_evidence(bad_evidence)
    assert review.passed is False
    assert len(review.reasons) > 0
    assert "Unsupported" in review.reasons[0]
    
    # Test with empty evidence
    review = critic.review_evidence([])
    assert review.passed is False
    assert "No evidence" in review.reasons[0]
