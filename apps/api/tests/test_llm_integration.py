"""
Test LLM integration for Milestone 2.
"""

import asyncio
import os

import pytest

from app.agents.analyzer import AnalyzerAgent
from app.llm.provider import LLMConfig, LLMFactory, set_llm_provider


def _llm_api_key() -> str:
    return os.environ.get("METAMIND_LLM_API_KEY", "")


requires_llm_key = pytest.mark.skipif(
    not _llm_api_key(),
    reason="METAMIND_LLM_API_KEY is required for live LLM integration tests",
)


def test_llm_provider_initialization():
    """Test that LLM provider can be initialized."""
    config = LLMConfig(
        provider="deepseek",
        api_key="test-key",
        base_url="https://api.deepseek.com",
        model="deepseek-chat",
    )
    
    provider = LLMFactory.create(config)
    assert provider is not None


@requires_llm_key
def test_llm_provider_completion():
    """Test basic LLM completion."""
    config = LLMConfig(
        provider="deepseek",
        api_key=_llm_api_key(),
        base_url="https://api.deepseek.com",
        model="deepseek-chat",
    )
    
    provider = LLMFactory.create(config)
    
    messages = [
        {"role": "system", "content": "You are a helpful assistant."},
        {"role": "user", "content": "Say 'Hello World' and nothing else."}
    ]
    
    response = asyncio.run(provider.complete(messages, temperature=0.1, max_tokens=10))
    
    assert response
    assert len(response) > 0
    print(f"LLM response: {response}")


@requires_llm_key
def test_llm_provider_json():
    """Test JSON mode completion."""
    config = LLMConfig(
        provider="deepseek",
        api_key=_llm_api_key(),
        base_url="https://api.deepseek.com",
        model="deepseek-chat",
    )
    
    provider = LLMFactory.create(config)
    
    messages = [
        {"role": "system", "content": "You are a helpful assistant that outputs JSON."},
        {"role": "user", "content": 'Output JSON with format: {"greeting": "Hello", "number": 42}'}
    ]
    
    response = asyncio.run(provider.complete_json(messages, temperature=0.1, max_tokens=50))
    
    assert isinstance(response, dict)
    assert "greeting" in response or "number" in response
    print(f"LLM JSON response: {response}")


@requires_llm_key
def test_analyzer_with_llm():
    """Test Analyzer with LLM-generated insights."""
    # Setup LLM provider
    config = LLMConfig(
        provider="deepseek",
        api_key=_llm_api_key(),
        base_url="https://api.deepseek.com",
        model="deepseek-chat",
    )
    provider = LLMFactory.create(config)
    set_llm_provider(provider)
    
    # Create analyzer with LLM enabled
    analyzer = AnalyzerAgent(use_llm=True)
    
    # Mock hero data
    mock_heroes = [
        {
            "hero": "Axe",
            "win_rate": 0.538,
            "pick_rate": 0.21,
            "ban_rate": 0.64,
            "pro_presence": 0.08,
            "patch_impact_score": 0.15,
            "trend_score": 0.6,
        }
    ]
    
    # Run analysis
    recommendations = asyncio.run(analyzer.analyze_meta_report(mock_heroes, "offlane"))
    
    assert len(recommendations) == 1
    hero = recommendations[0]
    
    assert hero.hero == "Axe"
    assert hero.meta_score > 0
    
    # Check LLM-generated content
    print(f"\n{'='*60}")
    print(f"Hero: {hero.hero}")
    print(f"Meta Score: {hero.meta_score}/100 (Tier {hero.recommendation})")
    print(f"Win Rate: {hero.win_rate:.1%}")
    print(f"\nReasons ({len(hero.reasons)}):")
    for i, reason in enumerate(hero.reasons, 1):
        print(f"  {i}. {reason}")
    
    print(f"\nPractice Advice ({len(hero.practice_advice)}):")
    for i, advice in enumerate(hero.practice_advice, 1):
        print(f"  {i}. {advice}")
    print(f"{'='*60}\n")
    
    # Verify LLM generated content
    if analyzer.llm_enabled:
        assert len(hero.reasons) > 0, "LLM should generate reasons"
        assert len(hero.practice_advice) > 0, "LLM should generate practice advice"
        assert all(len(r) > 10 for r in hero.reasons), "Reasons should be substantial"
        assert all(len(a) > 10 for a in hero.practice_advice), "Advice should be substantial"
    
    print("[PASS] LLM integration test passed!")


if __name__ == "__main__":
    print("Testing LLM Provider initialization...")
    test_llm_provider_initialization()
    print("[PASS] Passed\n")
    
    print("Testing LLM basic completion...")
    test_llm_provider_completion()
    print("[PASS] Passed\n")
    
    print("Testing LLM JSON mode...")
    test_llm_provider_json()
    print("[PASS] Passed\n")
    
    print("Testing Analyzer with LLM insights...")
    test_analyzer_with_llm()
    print("[PASS] All tests passed!")
