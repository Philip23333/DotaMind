from app.agentic.planning.controller import AgentController
from app.agentic.tools.stratz_tools import build_default_tool_registry
from app.core.config import Settings


def test_competition_scope_rules_are_generic_and_year_agnostic() -> None:
    prompt = AgentController(
        build_default_tool_registry(
            Settings(stratz_graphql_url="https://api.stratz.test/graphql", stratz_token="token")
        ),
        llm_enabled=False,
    )._system_prompt()
    assert "a missing edition year is not by itself a" in prompt
    assert "call its resolver without `year`" in prompt
    assert "Preserve an edition year explicitly supplied by the user" in prompt
    assert "现在TI的最新战况如何？" in prompt
    assert "TI 2025 最新战况如何？" in prompt
    assert "Resolve a named recurring Dota 2 competition." in prompt
    assert "Do not request clarification solely for a missing edition year." in prompt
    assert all(value not in prompt for value in ("2026", "10828", "9555"))
