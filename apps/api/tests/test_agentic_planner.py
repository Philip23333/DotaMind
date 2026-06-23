import asyncio
from typing import Any

from app.agentic.planner import AgenticPlanner
from app.agentic.stratz_tools import build_default_tool_registry
from app.core.config import Settings
from app.llm.provider import ToolCallResult


class FakeLLM:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload

    async def complete(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 1000,
    ) -> str:
        return ""

    async def complete_json(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 1000,
    ) -> dict[str, Any]:
        return self.payload

    async def complete_with_tools(
        self,
        messages: list[dict[str, str]],
        tools: list[dict[str, Any]],
        temperature: float = 0.2,
        max_tokens: int = 1000,
    ) -> ToolCallResult | None:
        return None


def _registry():
    return build_default_tool_registry(
        Settings(stratz_graphql_url="https://api.stratz.test/graphql", stratz_token="token")
    )


def _valid_plan_payload() -> dict[str, Any]:
    return {
        "status": "planned",
        "reason": "counter matchup can be answered with registered tools",
        "plan": {
            "intent": "counter_pick",
            "goal": "Fetch Lina matchup evidence.",
            "output_contract": "tool_results",
            "tool_calls": [
                {
                    "id": "resolve_target",
                    "tool": "resolve_hero",
                    "args": {"query": "Lina"},
                },
                {
                    "id": "get_matchups",
                    "tool": "stratz.hero_vs_hero_matchup",
                    "args": {
                        "hero_id": "$resolve_target.data.hero.hero_id",
                        "take": 5,
                    },
                },
            ],
            "required_evidence": [
                "hero_identity",
                "matchup_win_rate",
                "sample_size",
            ],
            "constraints": {"max_tool_calls": 6, "allow_mock": False},
        },
    }


def test_agentic_planner_accepts_valid_counter_pick_plan() -> None:
    planner = AgenticPlanner(_registry(), llm=FakeLLM(_valid_plan_payload()), llm_enabled=True)

    result = asyncio.run(planner.plan("enemy picked Lina, what should I pick?"))

    assert result.status == "planned"
    assert result.plan is not None
    assert result.plan.tool_calls[0].tool == "resolve_hero"


def test_agentic_planner_returns_insufficient_tools() -> None:
    planner = AgenticPlanner(
        _registry(),
        llm=FakeLLM(
            {
                "status": "insufficient_tools",
                "reason": "team reports require an unregistered team tool",
                "plan": None,
            }
        ),
        llm_enabled=True,
    )

    result = asyncio.run(planner.plan("How Team BB play lately?"))

    assert result.status == "insufficient_tools"
    assert result.plan is None


def test_agentic_planner_rejects_unknown_tool() -> None:
    payload = _valid_plan_payload()
    payload["plan"]["tool_calls"][1]["tool"] = "reports.team_report"
    planner = AgenticPlanner(_registry(), llm=FakeLLM(payload), llm_enabled=True)

    result = asyncio.run(planner.plan("How Team BB play lately?"))

    assert result.status == "error"
    assert "unknown tool" in result.errors[0]


def test_agentic_planner_rejects_hardcoded_hero_id() -> None:
    payload = _valid_plan_payload()
    payload["plan"]["tool_calls"][1]["args"]["hero_id"] = 25
    planner = AgenticPlanner(_registry(), llm=FakeLLM(payload), llm_enabled=True)

    result = asyncio.run(planner.plan("enemy picked Lina, what should I pick?"))

    assert result.status == "error"
    assert "hero_id must be" in result.errors[0]


def test_agentic_planner_rejects_mock_allowed() -> None:
    payload = _valid_plan_payload()
    payload["plan"]["constraints"]["allow_mock"] = True
    planner = AgenticPlanner(_registry(), llm=FakeLLM(payload), llm_enabled=True)

    result = asyncio.run(planner.plan("enemy picked Lina, what should I pick?"))

    assert result.status == "error"
    assert "allow_mock" in result.errors[0]


def test_agentic_planner_rejects_missing_required_evidence() -> None:
    payload = _valid_plan_payload()
    payload["plan"]["required_evidence"] = ["hero_identity"]
    planner = AgenticPlanner(_registry(), llm=FakeLLM(payload), llm_enabled=True)

    result = asyncio.run(planner.plan("enemy picked Lina, what should I pick?"))

    assert result.status == "error"
    assert "missing required evidence" in result.errors[0]


def test_agentic_planner_returns_error_when_disabled() -> None:
    planner = AgenticPlanner(_registry(), llm=FakeLLM(_valid_plan_payload()), llm_enabled=False)

    result = asyncio.run(planner.plan("enemy picked Lina, what should I pick?"))

    assert result.status == "error"
    assert "LLM planner is disabled" in result.reason
