import asyncio
from typing import Any

from app.agentic.planning.planner import AgenticPlanner
from app.agentic.tools.stratz_tools import build_default_tool_registry
from app.core.config import Settings
from app.llm.provider import LLMJSONDecodeError, ToolCallResult


class FakeLLM:
    def __init__(
        self,
        payload: dict[str, Any] | None = None,
        error: Exception | None = None,
    ) -> None:
        self.payload = payload
        self.error = error

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
        if self.error:
            raise self.error
        assert self.payload is not None
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
            "output_contract": "draft_advice",
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
    assert result.raw_output == _valid_plan_payload()
    assert [message["role"] for message in result.prompt_messages] == ["system", "user"]
    assert "Schema obedience rules" in result.prompt_messages[0]["content"]


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
    assert result.raw_output
    assert result.raw_output["status"] == "insufficient_tools"


def test_agentic_planner_exposes_raw_content_on_json_decode_error() -> None:
    planner = AgenticPlanner(
        _registry(),
        llm=FakeLLM(
            error=LLMJSONDecodeError(
                "Unterminated string",
                raw_content='{"status":"planned","reason":"cut',
                finish_reason="length",
            )
        ),
        llm_enabled=True,
    )

    result = asyncio.run(planner.plan("enemy picked Lina, what should I pick?"))

    assert result.status == "error"
    assert result.raw_output is None
    assert result.raw_content == '{"status":"planned","reason":"cut'
    assert result.finish_reason == "length"
    assert "LLMJSONDecodeError" in result.errors[0]


def test_agentic_planner_rejects_unknown_tool() -> None:
    payload = _valid_plan_payload()
    payload["plan"]["tool_calls"][1]["tool"] = "reports.team_report"
    planner = AgenticPlanner(_registry(), llm=FakeLLM(payload), llm_enabled=True)

    result = asyncio.run(planner.plan("How Team BB play lately?"))

    assert result.status == "error"
    assert "unknown tool" in result.errors[0]
    assert result.raw_output == payload


def test_agentic_planner_accepts_hardcoded_hero_id_when_schema_allows_int() -> None:
    payload = _valid_plan_payload()
    payload["plan"]["tool_calls"][1]["args"]["hero_id"] = 25
    planner = AgenticPlanner(_registry(), llm=FakeLLM(payload), llm_enabled=True)

    result = asyncio.run(planner.plan("enemy picked Lina, what should I pick?"))

    assert result.status == "planned"


def test_agentic_planner_accepts_lane_outcome_reference_from_any_previous_call_id() -> None:
    payload = _valid_plan_payload()
    payload["plan"]["tool_calls"][0]["id"] = "resolve_lina"
    payload["plan"]["tool_calls"][1]["tool"] = "stratz.lane_outcome"
    payload["plan"]["tool_calls"][1]["args"] = {
        "hero_id": "$resolve_lina.data.hero.hero_id",
        "is_with": False,
    }
    payload["plan"]["output_contract"] = "natural_language_answer"
    payload["plan"]["required_evidence"] = [
        "hero_identity",
        "lane_outcome",
        "sample_size",
    ]
    planner = AgenticPlanner(_registry(), llm=FakeLLM(payload), llm_enabled=True)

    result = asyncio.run(planner.plan("how does Lina lane?"))

    assert result.status == "planned"


def test_agentic_planner_rejects_lane_outcome_missing_is_with() -> None:
    payload = _valid_plan_payload()
    payload["plan"]["tool_calls"][0]["id"] = "resolve_lina"
    payload["plan"]["tool_calls"][1]["tool"] = "stratz.lane_outcome"
    payload["plan"]["tool_calls"][1]["args"] = {
        "hero_id": "$resolve_lina.data.hero.hero_id",
    }
    payload["plan"]["output_contract"] = "natural_language_answer"
    payload["plan"]["required_evidence"] = [
        "hero_identity",
        "lane_outcome",
        "sample_size",
    ]
    planner = AgenticPlanner(_registry(), llm=FakeLLM(payload), llm_enabled=True)

    result = asyncio.run(planner.plan("how does Lina lane?"))

    assert result.status == "error"
    assert any("stratz.lane_outcome invalid args" in item for item in result.errors)


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


def test_agentic_planner_rejects_counter_pick_tool_results_contract() -> None:
    payload = _valid_plan_payload()
    payload["plan"]["output_contract"] = "tool_results"
    planner = AgenticPlanner(_registry(), llm=FakeLLM(payload), llm_enabled=True)

    result = asyncio.run(planner.plan("enemy picked Lina, what should I pick?"))

    assert result.status == "error"
    assert "unknown output_contract: tool_results" in result.errors[0]


def test_agentic_planner_rejects_meta_list_contract() -> None:
    payload = _valid_plan_payload()
    payload["plan"]["output_contract"] = "meta_list"
    planner = AgenticPlanner(_registry(), llm=FakeLLM(payload), llm_enabled=True)

    result = asyncio.run(planner.plan("这版本什么三号位厉害？"))

    assert result.status == "error"
    assert "unknown output_contract: meta_list" in result.errors[0]


def test_agentic_planner_accepts_role_meta_report_evidence_contract() -> None:
    payload = {
        "status": "planned",
        "reason": "role meta can use hero stats",
        "plan": {
            "intent": "role_meta",
            "goal": "Find strong mid heroes.",
            "output_contract": "role_meta_report",
            "tool_calls": [
                {
                    "id": "mid_stats",
                    "tool": "opendota.hero_stats_by_role",
                    "args": {"role": "mid"},
                }
            ],
            "required_evidence": ["hero_stats", "role_fit", "sample_size"],
            "constraints": {"max_tool_calls": 6, "allow_mock": False},
        },
    }
    planner = AgenticPlanner(_registry(), llm=FakeLLM(payload), llm_enabled=True)

    result = asyncio.run(planner.plan("what mid heroes are strong?"))

    assert result.status == "planned"


def test_agentic_planner_accepts_team_recent_report_catalog_contract() -> None:
    payload = {
        "status": "planned",
        "reason": "team evidence can be answered with OpenDota tools",
        "plan": {
            "intent": "team_recent_performance",
            "goal": "Summarize Team BB recent form.",
            "output_contract": "team_recent_report",
            "tool_calls": [
                {
                    "id": "resolve_team",
                    "tool": "opendota.resolve_team",
                    "args": {"query": "Team BB"},
                },
                {
                    "id": "get_matches",
                    "tool": "opendota.team_recent_matches",
                    "args": {
                        "team_id": "$resolve_team.data.team.team_id",
                        "days": 30,
                    },
                },
                {
                    "id": "get_players",
                    "tool": "opendota.team_players",
                    "args": {
                        "team_id": "$resolve_team.data.team.team_id",
                        "current_only": True,
                    },
                },
                {
                    "id": "get_heroes",
                    "tool": "opendota.team_heroes",
                    "args": {"matches": "$get_matches.data.matches"},
                },
            ],
            "required_evidence": [
                "team_identity",
                "recent_matches",
                "current_players",
                "team_hero_usage",
            ],
            "constraints": {"max_tool_calls": 6, "allow_mock": False},
        },
    }
    planner = AgenticPlanner(_registry(), llm=FakeLLM(payload), llm_enabled=True)

    result = asyncio.run(planner.plan("How Team BB play lately?"))

    assert result.status == "planned"


def test_agentic_planner_rejects_bad_team_recent_report_contract() -> None:
    payload = {
        "status": "planned",
        "reason": "bad team evidence names",
        "plan": {
            "intent": "team_recent_performance",
            "goal": "Summarize Team BB recent form.",
            "output_contract": "team_recent_report",
            "tool_calls": [
                {
                    "id": "get_players",
                    "tool": "opendota.team_players",
                    "args": {
                        "team_id": "$resolve_team.data.team.team_id",
                        "current_roster": True,
                    },
                },
                {
                    "id": "get_heroes",
                    "tool": "opendota.team_heroes",
                    "args": {"team_id": "$resolve_team.data.team.team_id"},
                },
            ],
            "required_evidence": ["team_identity", "matches", "roster", "hero_usage"],
            "constraints": {"max_tool_calls": 6, "allow_mock": False},
        },
    }
    planner = AgenticPlanner(_registry(), llm=FakeLLM(payload), llm_enabled=True)

    result = asyncio.run(planner.plan("How Team BB play lately?"))

    assert result.status == "error"
    assert any(
        "unknown required_evidence: hero_usage, matches, roster" in item
        for item in result.errors
    )
    assert any(
        "opendota.team_players unknown args: current_roster" in item
        for item in result.errors
    )
    assert any("opendota.team_heroes unknown args: team_id" in item for item in result.errors)


def test_agentic_planner_prompt_contains_team_recent_catalog_example() -> None:
    planner = AgenticPlanner(_registry(), llm=FakeLLM(_valid_plan_payload()), llm_enabled=True)

    prompt = planner._system_prompt()

    assert "team_recent_report" in prompt
    assert "recent_matches" in prompt
    assert "current_players" in prompt
    assert "team_hero_usage" in prompt
    assert '"matches": "$get_matches.data.matches"' in prompt
    assert "evidence_produced" in prompt
    assert "allowed_arg_keys" in prompt
    assert "Do not invent aliases or synonyms" in prompt
    assert "required_evidence_names_must_be_exact" in prompt
    assert "recent_matches, do not" in prompt
    assert "- is_with: bool, required" in prompt
    assert "$<previous_call_id>.data.hero.hero_id" in prompt
    assert "DIVINE_IMMORTAL" in prompt
    assert (
        "do not use DIVINE or IMMORTAL separately" in prompt
        or "Map 冠绝/Immortal/Divine to DIVINE_IMMORTAL" in prompt
    )
    assert "$resolve_target.data.hero.hero_id" not in prompt


def test_agentic_planner_rejects_unknown_required_evidence() -> None:
    payload = {
        "status": "planned",
        "reason": "bad role meta evidence",
        "plan": {
            "intent": "role_meta",
            "goal": "Find strong mid heroes.",
            "output_contract": "role_meta_report",
            "tool_calls": [
                {
                    "id": "mid_stats",
                    "tool": "opendota.hero_stats_by_role",
                    "args": {"role": "mid"},
                }
            ],
            "required_evidence": ["hero_stats", "hero_name"],
            "constraints": {"max_tool_calls": 6, "allow_mock": False},
        },
    }
    planner = AgenticPlanner(_registry(), llm=FakeLLM(payload), llm_enabled=True)

    result = asyncio.run(planner.plan("what mid heroes are strong?"))

    assert result.status == "error"
    assert any("unknown required_evidence: hero_name" in item for item in result.errors)


def test_agentic_planner_rejects_role_meta_without_hero_stats() -> None:
    payload = {
        "status": "planned",
        "reason": "bad role meta evidence",
        "plan": {
            "intent": "role_meta",
            "goal": "Find strong mid heroes.",
            "output_contract": "role_meta_report",
            "tool_calls": [
                {
                    "id": "mid_stats",
                    "tool": "opendota.hero_stats_by_role",
                    "args": {"role": "mid"},
                }
            ],
            "required_evidence": ["role_fit"],
            "constraints": {"max_tool_calls": 6, "allow_mock": False},
        },
    }
    planner = AgenticPlanner(_registry(), llm=FakeLLM(payload), llm_enabled=True)

    result = asyncio.run(planner.plan("what mid heroes are strong?"))

    assert result.status == "error"
    assert any("missing required evidence: hero_stats" in item for item in result.errors)


def test_agentic_planner_accepts_patch_impact_plan() -> None:
    payload = {
        "status": "planned",
        "reason": "patch impact can be answered with local patch tools",
        "plan": {
            "intent": "patch_impact",
            "goal": "Summarize latest patch.",
            "output_contract": "patch_impact_report",
            "tool_calls": [
                {
                    "id": "patch",
                    "tool": "patch.get_records",
                    "args": {"patch": "latest"},
                }
            ],
            "required_evidence": ["patch_records"],
            "constraints": {"max_tool_calls": 6, "allow_mock": False},
        },
    }
    planner = AgenticPlanner(_registry(), llm=FakeLLM(payload), llm_enabled=True)

    result = asyncio.run(planner.plan("latest patch impact?"))

    assert result.status == "planned"


def test_agentic_planner_rejects_patch_impact_without_records_tool() -> None:
    payload = {
        "status": "planned",
        "reason": "bad patch plan",
        "plan": {
            "intent": "patch_impact",
            "goal": "Summarize latest patch.",
            "output_contract": "patch_impact_report",
            "tool_calls": [],
            "required_evidence": ["patch_records"],
            "constraints": {"max_tool_calls": 6, "allow_mock": False},
        },
    }
    planner = AgenticPlanner(_registry(), llm=FakeLLM(payload), llm_enabled=True)

    result = asyncio.run(planner.plan("latest patch impact?"))

    assert result.status == "error"
    assert "must use patch.get_records" in result.errors[0]


def test_agentic_planner_rejects_patch_impact_without_patch_records_evidence() -> None:
    payload = {
        "status": "planned",
        "reason": "bad patch plan",
        "plan": {
            "intent": "patch_impact",
            "goal": "Summarize latest patch.",
            "output_contract": "patch_impact_report",
            "tool_calls": [
                {
                    "id": "patch",
                    "tool": "patch.get_records",
                    "args": {"patch": "latest"},
                }
            ],
            "required_evidence": [],
            "constraints": {"max_tool_calls": 6, "allow_mock": False},
        },
    }
    planner = AgenticPlanner(_registry(), llm=FakeLLM(payload), llm_enabled=True)

    result = asyncio.run(planner.plan("latest patch impact?"))

    assert result.status == "error"
    assert "patch_records" in result.errors[0]


def test_agentic_planner_returns_error_when_disabled() -> None:
    planner = AgenticPlanner(_registry(), llm=FakeLLM(_valid_plan_payload()), llm_enabled=False)

    result = asyncio.run(planner.plan("enemy picked Lina, what should I pick?"))

    assert result.status == "error"
    assert "LLM planner is disabled" in result.reason
