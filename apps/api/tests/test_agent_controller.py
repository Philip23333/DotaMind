import asyncio
from typing import Any

from app.agentic.conversation.models import ConversationMessage
from app.agentic.graph import AgentGraphRunner
from app.agentic.nodes.decision_validate import decision_validate_node
from app.agentic.planning.controller import AgentController, AgentControllerResult
from app.agentic.planning.decisions import (
    CapabilityBoundaryDecision,
    DirectAnswerDecision,
    ToolPlanDecision,
)
from app.agentic.state import AgentRunState
from app.agentic.tools.stratz_tools import build_default_tool_registry
from app.core.config import Settings
from app.llm.provider import LLMJSONDecodeError, ToolCallResult


class FakeLLM:
    """Test double for the controller LLM.

    payload accepts either a single dict (returned on every call) or a list of
    dict | Exception items consumed in order across retry attempts. An Exception
    item is raised on that attempt to simulate a decode/transport failure.
    """

    def __init__(
        self,
        payload: dict[str, Any] | list[Any] | None = None,
        error: Exception | None = None,
    ) -> None:
        self._error = error
        if isinstance(payload, list):
            self._sequence: list[Any] | None = list(payload)
            self._single: dict[str, Any] | None = None
        else:
            self._sequence = None
            self._single = payload
        self._index = 0
        self.calls = 0
        self.received_messages: list[list[dict[str, str]]] = []

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
        self.calls += 1
        self.received_messages.append([dict(message) for message in messages])
        if self._error is not None:
            raise self._error
        if self._sequence is not None:
            if self._index >= len(self._sequence):
                raise AssertionError("FakeLLM sequence exhausted")
            item = self._sequence[self._index]
            self._index += 1
            if isinstance(item, Exception):
                raise item
            return _controller_payload(item)
        assert self._single is not None
        return _controller_payload(self._single)

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
        "kind": "tool_plan",
        "plan": {
            "intent": "hero_matchup_ranking",
            "goal": "Fetch Lina matchup ranking evidence.",
            "output_contract": "natural_language_answer",
            "tool_calls": [
                {
                    "id": "resolve_target",
                    "tool": "resolve_hero",
                    "args": {"query": "Lina"},
                },
                {
                    "id": "get_ranking",
                    "tool": "stratz.hero_matchup_ranking",
                    "args": {
                        "hero_id": "$resolve_target.data.hero.hero_id",
                        "side": "vs",
                        "take": 5,
                    },
                },
            ],
            "required_evidence": [
                "hero_identity",
                "matchup_ranking_row",
                "sample_size",
            ],
            "constraints": {"max_tool_calls": 6, "allow_mock": False},
        },
    }


def _pair_lane_mid_plan_payload() -> dict[str, Any]:
    return {
        "kind": "tool_plan",
        "plan": {
            "intent": "pair_lane_outcome",
            "goal": "Compare Storm Spirit and Lina lane and match outcomes.",
            "output_contract": "natural_language_answer",
            "context": {
                "bracket": ["DIVINE_IMMORTAL"],
                "weeks_back": None,
                "position_ids": ["POSITION_2"],
                "region_ids": None,
                "game_mode_ids": None,
            },
            "tool_calls": [
                {
                    "id": "resolve_storm",
                    "tool": "resolve_hero",
                    "args": {"query": "蓝猫"},
                },
                {
                    "id": "resolve_lina",
                    "tool": "resolve_hero",
                    "args": {"query": "火女"},
                },
                {
                    "id": "pair_lane",
                    "tool": "stratz.pair_lane_outcome",
                    "args": {
                        "hero_id": "$resolve_storm.data.hero.hero_id",
                        "partner_hero_id": "$resolve_lina.data.hero.hero_id",
                        "is_with": False,
                    },
                },
            ],
            "required_evidence": [
                "hero_identity",
                "pair_lane_outcome",
                "sample_size",
            ],
            "constraints": {"max_tool_calls": 6, "allow_mock": False},
        },
    }


def _controller_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Keep the catalog-validation fixtures compact while using the new contract."""
    if payload.get("status") == "planned":
        return {"kind": "tool_plan", "plan": payload.get("plan")}
    if payload.get("status") == "insufficient_tools":
        return {
            "kind": "capability_boundary",
            "intent": "unsupported_capability",
            "reason": payload.get("reason") or "Unsupported by registered tools.",
        }
    return payload


def _result_plan(result: AgentControllerResult):
    assert isinstance(result.decision, ToolPlanDecision)
    return result.decision.plan


def test_agent_controller_accepts_valid_counter_pick_plan() -> None:
    controller = AgentController(
        _registry(), llm=FakeLLM(_valid_plan_payload()), llm_enabled=True, planner_max_retries=0
    )

    result = asyncio.run(controller.decide("enemy picked Lina, what should I pick?"))

    assert result.status == "decided"
    assert _result_plan(result).tool_calls[0].tool == "resolve_hero"
    assert result.evidence_resolution.required_evidence_sources[
        "matchup_ranking_row"
    ] == ["planner", "tool:stratz.hero_matchup_ranking"]
    assert result.raw_output == _valid_plan_payload()
    assert [message["role"] for message in result.prompt_messages] == ["system", "user"]
    assert "Schema obedience rules" in result.prompt_messages[0]["content"]


def test_agent_controller_returns_capability_boundary() -> None:
    controller = AgentController(
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

    result = asyncio.run(controller.decide("How Team BB play lately?"))

    assert result.status == "decided"
    assert isinstance(result.decision, CapabilityBoundaryDecision)
    assert result.raw_output
    assert result.raw_output["kind"] == "capability_boundary"


def test_agent_controller_accepts_catalog_static_query_plans() -> None:
    cases = [
        (
            "莉娜有哪些技能？",
            {
                "kind": "tool_plan",
                "plan": {
                    "intent": "hero_abilities",
                    "goal": "Return Lina's official ability definitions.",
                    "output_contract": "natural_language_answer",
                    "tool_calls": [
                        {
                            "id": "resolve_lina",
                            "tool": "resolve_hero",
                            "args": {"query": "莉娜"},
                        },
                        {
                            "id": "abilities",
                            "tool": "dota.hero_abilities",
                            "args": {
                                "hero_id": "$resolve_lina.data.hero.hero_id"
                            },
                        },
                        {
                            "id": "talents",
                            "tool": "dota.hero_talent_tree",
                            "args": {
                                "hero_id": "$resolve_lina.data.hero.hero_id"
                            },
                        },
                    ],
                    "required_evidence": [
                        "hero_identity",
                        "hero_ability",
                        "hero_talent_tree",
                    ],
                },
            },
            ["resolve_hero", "dota.hero_abilities", "dota.hero_talent_tree"],
        ),
        (
            "棒击大地是什么？",
            {
                "kind": "tool_plan",
                "plan": {
                    "intent": "single_hero_ability",
                    "goal": "Return the official Boundless Strike definition.",
                    "output_contract": "natural_language_answer",
                    "tool_calls": [
                        {
                            "id": "resolve_monkey_king",
                            "tool": "resolve_hero",
                            "args": {"query": "齐天大圣"},
                        },
                        {
                            "id": "abilities",
                            "tool": "dota.hero_abilities",
                            "args": {
                                "hero_id": "$resolve_monkey_king.data.hero.hero_id"
                            },
                        },
                    ],
                    "required_evidence": ["hero_identity", "hero_ability"],
                },
            },
            ["resolve_hero", "dota.hero_abilities"],
        ),
        (
            "莉娜的属性和天赋树",
            {
                "kind": "tool_plan",
                "plan": {
                    "intent": "hero_attributes_and_talents",
                    "goal": "Return Lina's official attributes and talent tree.",
                    "output_contract": "natural_language_answer",
                    "tool_calls": [
                        {
                            "id": "resolve_lina",
                            "tool": "resolve_hero",
                            "args": {"query": "莉娜"},
                        },
                        {
                            "id": "attributes",
                            "tool": "dota.hero_attributes",
                            "args": {
                                "hero_id": "$resolve_lina.data.hero.hero_id"
                            },
                        },
                        {
                            "id": "talents",
                            "tool": "dota.hero_talent_tree",
                            "args": {
                                "hero_id": "$resolve_lina.data.hero.hero_id"
                            },
                        },
                    ],
                    "required_evidence": [
                        "hero_identity",
                        "hero_attributes",
                        "hero_talent_tree",
                    ],
                },
            },
            ["resolve_hero", "dota.hero_attributes", "dota.hero_talent_tree"],
        ),
        (
            "黑皇杖多少钱，怎么合成？",
            {
                "kind": "tool_plan",
                "plan": {
                    "intent": "item_definition_and_recipe",
                    "goal": "Return BKB's official price and recipe.",
                    "output_contract": "natural_language_answer",
                    "tool_calls": [
                        {
                            "id": "resolve_bkb",
                            "tool": "resolve_item",
                            "args": {"query": "黑皇杖"},
                        },
                        {
                            "id": "item_info",
                            "tool": "dota.item_info",
                            "args": {
                                "item_id": "$resolve_bkb.data.item.item_id"
                            },
                        },
                    ],
                    "required_evidence": [
                        "item_identity",
                        "item_definition",
                        "item_recipe",
                    ],
                },
            },
            ["resolve_item", "dota.item_info"],
        ),
    ]

    for query, payload, expected_tools in cases:
        controller = AgentController(
            _registry(),
            llm=FakeLLM(payload),
            llm_enabled=True,
            planner_max_retries=0,
        )
        result = asyncio.run(controller.decide(query))

        assert result.status == "decided"
        assert [call.tool for call in _result_plan(result).tool_calls] == expected_tools


def test_agent_controller_keeps_static_catalog_recommendation_boundary() -> None:
    controller = AgentController(
        _registry(),
        llm=FakeLLM(
            {
                "kind": "capability_boundary",
                "intent": "item_build_recommendation",
                "reason": "No registered statistical item build tool is available.",
            }
        ),
        llm_enabled=True,
        planner_max_retries=0,
    )

    result = asyncio.run(controller.decide("莉娜应该出什么装备，哪个胜率最高？"))

    assert result.status == "decided"
    assert isinstance(result.decision, CapabilityBoundaryDecision)


def test_agent_controller_rejects_unknown_decision_fields() -> None:
    controller = AgentController(
        _registry(),
        llm=FakeLLM(
            {
                "kind": "capability_boundary",
                "intent": "unsupported",
                "reason": "no tool",
                "plan": {"unexpected": "must not be ignored"},
            }
        ),
        llm_enabled=True,
        planner_max_retries=0,
    )

    result = asyncio.run(controller.decide("unsupported request"))

    assert result.status == "error"
    assert result.failure_type == "decision_validation_error"
    assert any("Extra inputs are not permitted" in error for error in result.errors)


def test_agentic_planner_exposes_raw_content_on_json_decode_error() -> None:
    planner = AgentController(
        _registry(),
        llm=FakeLLM(
            error=LLMJSONDecodeError(
                "Unterminated string",
                raw_content='{"status":"planned","reason":"cut',
                finish_reason="length",
            )
        ),
        llm_enabled=True,
        planner_max_retries=0,
    )

    result = asyncio.run(planner.decide("enemy picked Lina, what should I pick?"))

    assert result.status == "error"
    assert result.raw_output is None
    assert result.raw_content == '{"status":"planned","reason":"cut'
    assert result.finish_reason == "length"
    assert "LLMJSONDecodeError" in result.errors[0]


def test_agentic_planner_rejects_unknown_tool() -> None:
    payload = _valid_plan_payload()
    payload["plan"]["tool_calls"][1]["tool"] = "reports.team_report"
    planner = AgentController(
        _registry(), llm=FakeLLM(payload), llm_enabled=True, planner_max_retries=0
    )

    result = asyncio.run(planner.decide("How Team BB play lately?"))

    assert result.status == "error"
    assert "unknown tool" in result.errors[0]
    assert result.raw_output == payload


def test_agentic_planner_rejects_hardcoded_hero_id() -> None:
    payload = _valid_plan_payload()
    payload["plan"]["tool_calls"][1]["args"]["hero_id"] = 25
    planner = AgentController(
        _registry(), llm=FakeLLM(payload), llm_enabled=True, planner_max_retries=0
    )

    result = asyncio.run(planner.decide("enemy picked Lina, what should I pick?"))

    assert result.status == "error"
    assert any("must reference" in error for error in result.errors)


def test_agentic_planner_accepts_pair_lane_outcome_reference_from_any_previous_call_id() -> None:
    payload = _valid_plan_payload()
    payload["plan"]["tool_calls"] = [
        {"id": "resolve_sk", "tool": "resolve_hero", "args": {"query": "骷髅王"}},
        {"id": "resolve_aa", "tool": "resolve_hero", "args": {"query": "冰魂"}},
        {
            "id": "pair_lane",
            "tool": "stratz.pair_lane_outcome",
            "args": {
                "hero_id": "$resolve_sk.data.hero.hero_id",
                "partner_hero_id": "$resolve_aa.data.hero.hero_id",
                "is_with": True,
            },
        },
    ]
    payload["plan"]["output_contract"] = "natural_language_answer"
    payload["plan"]["required_evidence"] = [
        "hero_identity",
        "pair_lane_outcome",
        "sample_size",
    ]
    planner = AgentController(
        _registry(), llm=FakeLLM(payload), llm_enabled=True, planner_max_retries=0
    )

    result = asyncio.run(planner.decide("how does SK + AA lane?"))

    assert result.status == "decided"


def test_agentic_planner_rejects_pair_lane_outcome_missing_is_with() -> None:
    payload = _valid_plan_payload()
    payload["plan"]["tool_calls"] = [
        {"id": "resolve_sk", "tool": "resolve_hero", "args": {"query": "骷髅王"}},
        {"id": "resolve_aa", "tool": "resolve_hero", "args": {"query": "冰魂"}},
        {
            "id": "pair_lane",
            "tool": "stratz.pair_lane_outcome",
            "args": {
                "hero_id": "$resolve_sk.data.hero.hero_id",
                "partner_hero_id": "$resolve_aa.data.hero.hero_id",
            },
        },
    ]
    payload["plan"]["output_contract"] = "natural_language_answer"
    payload["plan"]["required_evidence"] = [
        "hero_identity",
        "pair_lane_outcome",
        "sample_size",
    ]
    planner = AgentController(
        _registry(), llm=FakeLLM(payload), llm_enabled=True, planner_max_retries=0
    )

    result = asyncio.run(planner.decide("how does SK + AA lane?"))

    assert result.status == "error"
    assert any("stratz.pair_lane_outcome invalid args" in item for item in result.errors)


def test_agentic_planner_rejects_mock_allowed() -> None:
    payload = _valid_plan_payload()
    payload["plan"]["constraints"]["allow_mock"] = True
    planner = AgentController(
        _registry(), llm=FakeLLM(payload), llm_enabled=True, planner_max_retries=0
    )

    result = asyncio.run(planner.decide("enemy picked Lina, what should I pick?"))

    assert result.status == "error"
    assert "allow_mock" in result.errors[0]


def test_agentic_planner_rejects_missing_required_evidence() -> None:
    payload = {
        "status": "planned",
        "reason": "patch impact requires patch_records",
        "plan": {
            "intent": "patch_impact",
            "goal": "Patch summary.",
            "output_contract": "patch_impact_report",
            "tool_calls": [
                {"id": "patch", "tool": "patch.get_records", "args": {"patch": "latest"}},
            ],
            "required_evidence": ["hero_identity"],
            "constraints": {"max_tool_calls": 6, "allow_mock": False},
        },
    }
    planner = AgentController(
        _registry(), llm=FakeLLM(payload), llm_enabled=True, planner_max_retries=0
    )

    result = asyncio.run(planner.decide("what changed in 7.41d?"))

    assert result.status == "error"
    assert "not producible by selected tools" in " ".join(result.errors)


def test_agentic_planner_rejects_matchup_tool_results_contract() -> None:
    payload = _valid_plan_payload()
    payload["plan"]["output_contract"] = "tool_results"
    planner = AgentController(
        _registry(), llm=FakeLLM(payload), llm_enabled=True, planner_max_retries=0
    )

    result = asyncio.run(planner.decide("enemy picked Lina, what should I pick?"))

    assert result.status == "error"
    assert "unknown output_contract: tool_results" in " ".join(result.errors)


def test_agentic_planner_rejects_meta_list_contract() -> None:
    payload = _valid_plan_payload()
    payload["plan"]["output_contract"] = "meta_list"
    planner = AgentController(
        _registry(), llm=FakeLLM(payload), llm_enabled=True, planner_max_retries=0
    )

    result = asyncio.run(planner.decide("这版本什么三号位厉害？"))

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
    planner = AgentController(
        _registry(), llm=FakeLLM(payload), llm_enabled=True, planner_max_retries=0
    )

    result = asyncio.run(planner.decide("what mid heroes are strong?"))

    assert result.status == "decided"


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
    planner = AgentController(
        _registry(), llm=FakeLLM(payload), llm_enabled=True, planner_max_retries=0
    )

    result = asyncio.run(planner.decide("How Team BB play lately?"))

    assert result.status == "decided"


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
    planner = AgentController(
        _registry(), llm=FakeLLM(payload), llm_enabled=True, planner_max_retries=0
    )

    result = asyncio.run(planner.decide("How Team BB play lately?"))

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
    planner = AgentController(
        _registry(), llm=FakeLLM(_valid_plan_payload()), llm_enabled=True, planner_max_retries=0
    )

    prompt = planner._system_prompt()

    assert "team_recent_report" in prompt
    assert "recent_matches" in prompt
    assert "current_players" in prompt
    assert "team_hero_usage" in prompt
    assert "evidence_produced" in prompt
    assert "allowed_arg_keys" in prompt
    assert "Do not invent aliases or synonyms" in prompt
    assert "recent_matches, do not" in prompt
    assert "answer` MUST be a concise, non-empty answer" in prompt
    assert "This direct answer does not create an EvidenceGraph" in prompt
    assert "- is_with: bool, required" in prompt
    assert "$<previous_call_id>.data.hero.hero_id" in prompt
    assert "DIVINE_IMMORTAL" in prompt
    assert "Map 冠绝/Immortal/Divine to DIVINE_IMMORTAL" in prompt
    assert "$resolve_target.data.hero.hero_id" not in prompt
    # Slimmed: redundant meta-rule markers and the inline example are gone.
    assert "produced_evidence_names_must_be_exact" not in prompt
    assert "required_evidence_names_must_be_exact" not in prompt
    assert '"matches": "$get_matches.data.matches"' not in prompt


def test_direct_answer_uses_model_answer_without_retry() -> None:
    registry = _registry()
    llm = FakeLLM(
        {
            "kind": "direct_answer",
            "intent": "conversation_recall",
            "answer": "用户之前提到想练 Lina。",
        }
    )
    controller = AgentController(
        registry,
        llm=llm,
        llm_enabled=True,
        planner_max_retries=2,
    )
    recent_messages = [
        ConversationMessage(
            turn_index=1,
            role="assistant",
            content="记录了用户想练 Lina。",
        )
    ]

    state = asyncio.run(
        AgentGraphRunner(controller, registry).run(
            AgentRunState(
                query="我上次提到的是谁？",
                game="dota2",
                recent_messages=recent_messages,
            )
        )
    )

    assert llm.calls == 1
    assert state.status == "ok"
    assert isinstance(state.decision, DirectAnswerDecision)
    assert state.decision.answer == "用户之前提到想练 Lina。"
    assert state.answer is not None
    assert state.answer.summary == "用户之前提到想练 Lina。"


def test_controller_accepts_tool_plan_when_history_lacks_requested_lane_metric() -> None:
    history = [
        ConversationMessage(
            turn_index=1,
            role="user",
            content="冠绝分段，中路蓝猫对火女的胜率怎么样？",
        ),
        ConversationMessage(
            turn_index=2,
            role="assistant",
            content="蓝猫对火女的整局胜率是46.25%。",
        ),
    ]
    controller = AgentController(
        _registry(),
        llm=FakeLLM(_pair_lane_mid_plan_payload()),
        llm_enabled=True,
        planner_max_retries=0,
    )

    result = asyncio.run(
        controller.decide(
            "对线胜率与整局胜率分别是多少？",
            recent_messages=history,
        )
    )

    assert result.status == "decided"
    plan = _result_plan(result)
    assert plan.context.bracket == ["DIVINE_IMMORTAL"]
    assert plan.context.position_ids == ["POSITION_2"]
    assert [call.tool for call in plan.tool_calls] == [
        "resolve_hero",
        "resolve_hero",
        "stratz.pair_lane_outcome",
    ]
    assert "pair_lane_outcome" in plan.required_evidence


def test_controller_accepts_direct_answer_when_history_contains_all_metrics() -> None:
    history = [
        ConversationMessage(
            turn_index=1,
            role="assistant",
            content="冠绝分段，中路蓝猫对火女的对线胜率是11.70%，整局胜率是46.25%。",
        )
    ]
    controller = AgentController(
        _registry(),
        llm=FakeLLM(
            {
                "kind": "direct_answer",
                "intent": "pair_lane_outcome",
                "answer": "对线胜率11.70%，整局胜率46.25%。",
            }
        ),
        llm_enabled=True,
        planner_max_retries=0,
    )

    result = asyncio.run(
        controller.decide(
            "对线胜率与整局胜率分别是多少？",
            recent_messages=history,
        )
    )

    assert result.status == "decided"
    assert isinstance(result.decision, DirectAnswerDecision)
    assert result.decision.answer == "对线胜率11.70%，整局胜率46.25%。"


def test_malformed_direct_answers_remain_decision_shape_errors() -> None:
    for invalid_answer in ({"text": "错误类型"}, "x" * 1001):
        llm = FakeLLM(
            {
                "kind": "direct_answer",
                "intent": "conversation_recall",
                "answer": invalid_answer,
            }
        )
        controller = AgentController(
            _registry(),
            llm=llm,
            llm_enabled=True,
            planner_max_retries=0,
        )

        result = asyncio.run(controller.decide("我上次问了什么？"))

        assert llm.calls == 1
        assert result.status == "error"
        assert result.failure_type == "decision_validation_error"
        assert any("answer" in error for error in result.errors)


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
    planner = AgentController(
        _registry(), llm=FakeLLM(payload), llm_enabled=True, planner_max_retries=0
    )

    result = asyncio.run(planner.decide("what mid heroes are strong?"))

    assert result.status == "error"
    assert any("unknown required_evidence: hero_name" in item for item in result.errors)


def test_agent_controller_adds_mandatory_role_meta_evidence() -> None:
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
    planner = AgentController(
        _registry(), llm=FakeLLM(payload), llm_enabled=True, planner_max_retries=0
    )

    result = asyncio.run(planner.decide("what mid heroes are strong?"))

    assert result.status == "decided"
    assert result.evidence_resolution.effective_required_evidence == [
        "hero_stats",
        "role_fit",
    ]


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
    planner = AgentController(
        _registry(), llm=FakeLLM(payload), llm_enabled=True, planner_max_retries=0
    )

    result = asyncio.run(planner.decide("latest patch impact?"))

    assert result.status == "decided"


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
    planner = AgentController(
        _registry(), llm=FakeLLM(payload), llm_enabled=True, planner_max_retries=0
    )

    result = asyncio.run(planner.decide("latest patch impact?"))

    assert result.status == "error"
    assert "at least one tool call" in result.errors[0]


def test_agent_controller_adds_contract_and_tool_patch_evidence() -> None:
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
    planner = AgentController(
        _registry(), llm=FakeLLM(payload), llm_enabled=True, planner_max_retries=0
    )

    result = asyncio.run(planner.decide("latest patch impact?"))

    assert result.status == "decided"
    assert result.evidence_resolution.effective_required_evidence == ["patch_records"]
    assert result.evidence_resolution.required_evidence_sources == {
        "patch_records": ["contract:patch_impact_report", "tool:patch.get_records"]
    }


def test_agentic_planner_returns_error_when_disabled() -> None:
    planner = AgentController(_registry(), llm=FakeLLM(_valid_plan_payload()), llm_enabled=False)

    result = asyncio.run(planner.decide("enemy picked Lina, what should I pick?"))

    assert result.status == "error"
    assert "LLM controller is disabled" in result.reason


def test_agentic_planner_retries_on_validation_error_then_succeeds() -> None:
    bad_payload = _valid_plan_payload()
    bad_payload["plan"]["required_evidence"] = [
        "hero_identity",
        "matchup_ranking_row",
        "hero_name",  # unknown evidence kind -> validation rejects
    ]
    good_payload = _valid_plan_payload()
    planner = AgentController(
        _registry(),
        llm=FakeLLM([bad_payload, good_payload]),
        llm_enabled=True,
        planner_max_retries=2,
    )

    result = asyncio.run(planner.decide("enemy picked Lina, what should I pick?"))

    assert result.status == "decided"
    assert _result_plan(result) is not None
    assert [message["role"] for message in result.prompt_messages] == [
        "system",
        "user",
        "assistant",
        "user",
    ]


def test_agentic_planner_retries_on_missing_plan_then_succeeds() -> None:
    shape_error_payload = {
        "status": "planned",
        "reason": "forgot the plan",
        "plan": None,
    }
    good_payload = _valid_plan_payload()
    planner = AgentController(
        _registry(),
        llm=FakeLLM([shape_error_payload, good_payload]),
        llm_enabled=True,
        planner_max_retries=2,
    )

    result = asyncio.run(planner.decide("enemy picked Lina, what should I pick?"))

    assert result.status == "decided"
    assert [message["role"] for message in result.prompt_messages] == [
        "system",
        "user",
        "assistant",
        "user",
    ]


def test_agentic_planner_exhausts_retries_and_returns_error() -> None:
    bad_payload = _valid_plan_payload()
    bad_payload["plan"]["required_evidence"] = ["hero_identity", "hero_name"]
    planner = AgentController(
        _registry(),
        llm=FakeLLM(bad_payload),
        llm_enabled=True,
        planner_max_retries=2,
    )

    result = asyncio.run(planner.decide("enemy picked Lina, what should I pick?"))

    assert result.status == "error"
    assert any("hero_name" in error for error in result.errors)
    # 1 initial attempt + 2 retries => 2 (assistant, user) feedback pairs.
    assert [message["role"] for message in result.prompt_messages] == [
        "system",
        "user",
        "assistant",
        "user",
        "assistant",
        "user",
    ]


def test_agentic_planner_no_retry_when_max_retries_zero() -> None:
    bad_payload = _valid_plan_payload()
    bad_payload["plan"]["required_evidence"] = ["hero_identity", "hero_name"]
    planner = AgentController(
        _registry(),
        llm=FakeLLM(bad_payload),
        llm_enabled=True,
        planner_max_retries=0,
    )

    result = asyncio.run(planner.decide("enemy picked Lina, what should I pick?"))

    assert result.status == "error"
    assert [message["role"] for message in result.prompt_messages] == [
        "system",
        "user",
    ]


# --- sample-policy integration (stage 1) ------------------------------------

# Sentinel meaning "do not put min_sample_size in the args dict at all".
_OMIT = object()


def _matchup_payload(min_sample_size: Any = _OMIT) -> dict[str, Any]:
    """A valid matchup plan. min_sample_size=_OMIT leaves the arg out entirely;
    any other value (incl. None) is written into args verbatim."""
    args: dict[str, Any] = {
        "hero_id": "$resolve_target.data.hero.hero_id",
        "side": "vs",
        "take": 5,
    }
    if min_sample_size is not _OMIT:
        args["min_sample_size"] = min_sample_size
    return {
        "status": "planned",
        "reason": "matchup ranking can be answered with registered tools",
        "plan": {
            "intent": "hero_matchup_ranking",
            "goal": "Fetch Lina matchup ranking evidence.",
            "output_contract": "natural_language_answer",
            "tool_calls": [
                {"id": "resolve_target", "tool": "resolve_hero", "args": {"query": "Lina"}},
                {"id": "get_ranking", "tool": "stratz.hero_matchup_ranking", "args": args},
            ],
            "required_evidence": ["hero_identity", "matchup_ranking_row", "sample_size"],
            "constraints": {"max_tool_calls": 6, "allow_mock": False},
        },
    }


def test_agentic_planner_backfills_sample_policy_default_when_omitted() -> None:
    # No signal -> planner omits -> post-process fills default (2000) + provenance.
    planner = AgentController(
        _registry(), llm=FakeLLM(_matchup_payload()), llm_enabled=True, planner_max_retries=0
    )

    result = asyncio.run(planner.decide("enemy picked Lina, what should I pick?"))

    assert result.status == "decided"
    assert _result_plan(result).tool_calls[1].args["min_sample_size"] == 2000
    applied = _result_plan(result).metadata["policy_applied"]
    assert [r["tool_call_id"] for r in applied] == ["get_ranking"]
    assert applied[0]["mode"] == "default"

    state = AgentRunState(
        query="enemy picked Lina, what should I pick?",
        game="dota2",
        decision=result.decision,
        decision_kind="tool_plan",
        plan=_result_plan(result),
        planner_required_evidence=result.evidence_resolution.planner_required_evidence,
        effective_required_evidence=result.evidence_resolution.effective_required_evidence,
        required_evidence_sources=result.evidence_resolution.required_evidence_sources,
    )
    decision_validate_node(state, _registry())
    assert len(_result_plan(result).metadata["policy_applied"]) == 1


def test_agentic_planner_preserves_explicit_relaxed_sample_size() -> None:
    # "冷门也行" -> LLM chose relaxed (500). Preserved, no provenance.
    planner = AgentController(
        _registry(), llm=FakeLLM(_matchup_payload(500)), llm_enabled=True, planner_max_retries=0
    )

    result = asyncio.run(planner.decide("Lina 克制谁？冷门也行"))

    assert result.status == "decided"
    assert _result_plan(result).tool_calls[1].args["min_sample_size"] == 500
    assert _result_plan(result).metadata.get("policy_applied") is None


def test_agentic_planner_preserves_explicit_strict_sample_size() -> None:
    # "稳健" -> LLM chose strict (5000). Preserved, no provenance.
    planner = AgentController(
        _registry(), llm=FakeLLM(_matchup_payload(5000)), llm_enabled=True, planner_max_retries=0
    )

    result = asyncio.run(planner.decide("Lina 克制谁？要稳健大样本"))

    assert result.status == "decided"
    assert _result_plan(result).tool_calls[1].args["min_sample_size"] == 5000
    assert _result_plan(result).metadata.get("policy_applied") is None


def test_agentic_planner_preserves_explicit_user_named_sample_size() -> None:
    # "至少 3000 场" -> explicit (3000), overriding policy tiers. Preserved.
    planner = AgentController(
        _registry(), llm=FakeLLM(_matchup_payload(3000)), llm_enabled=True, planner_max_retries=0
    )

    result = asyncio.run(planner.decide("Lina 克制谁？至少 3000 场样本"))

    assert result.status == "decided"
    assert _result_plan(result).tool_calls[1].args["min_sample_size"] == 3000
    assert _result_plan(result).metadata.get("policy_applied") is None


def test_agentic_planner_treats_null_sample_size_as_omitted() -> None:
    # LLM emitted JSON null — without backfill validate would reject it as
    # not-an-int. Post-process converts null -> default and records provenance.
    planner = AgentController(
        _registry(), llm=FakeLLM(_matchup_payload(None)), llm_enabled=True, planner_max_retries=0
    )

    result = asyncio.run(planner.decide("enemy picked Lina, what should I pick?"))

    assert result.status == "decided"
    assert _result_plan(result).tool_calls[1].args["min_sample_size"] == 2000
    applied = _result_plan(result).metadata["policy_applied"]
    assert [r["tool_call_id"] for r in applied] == ["get_ranking"]


def test_agentic_planner_prompt_contains_sample_policy_table() -> None:
    planner = AgentController(
        _registry(), llm=FakeLLM(_valid_plan_payload()), llm_enabled=True, planner_max_retries=0
    )

    prompt = planner._system_prompt()

    assert "Sample-size policy" in prompt
    assert "explicit > strict > relaxed > default" in prompt
    assert "stratz.hero_matchup_ranking.min_sample_size" in prompt
    # Scattered ad-hoc thresholds were removed from selection_mode sections.
    assert "500-800" not in prompt


def _player_hero_performance_payload() -> dict[str, Any]:
    return {
        "status": "planned",
        "reason": "player hero win rates can be answered with player_hero_performance",
        "plan": {
            "intent": "player_hero_performance",
            "goal": "Recent hero win rates for player 853634884.",
            "output_contract": "natural_language_answer",
            "context": {
                "bracket": None,
                "weeks_back": None,
                "position_ids": None,
                "region_ids": None,
                "game_mode_ids": None,
            },
            "tool_calls": [
                {
                    "id": "confirm_player",
                    "tool": "stratz.player_profile",
                    "args": {"steam_account_id": 853634884},
                },
                {
                    "id": "heroperf",
                    "tool": "stratz.player_hero_performance",
                    "args": {
                        "steam_account_id": "$confirm_player.data.confirmed_steam_account_id",
                        "take": 15,
                        "match_take": 20,
                    },
                }
            ],
            "required_evidence": ["player_hero_performance", "sample_size"],
            "constraints": {"max_tool_calls": 6, "allow_mock": False},
        },
    }


def test_agentic_planner_prompt_contains_player_routing() -> None:
    planner = AgentController(
        _registry(), llm=FakeLLM(_valid_plan_payload()), llm_enabled=True, planner_max_retries=0
    )

    prompt = planner._system_prompt()

    # player tools are registered and surfaced in the rendered catalog
    assert "stratz.player_profile" in prompt
    assert "stratz.player_recent_matches" in prompt
    assert "stratz.player_hero_performance" in prompt
    # routing + param-semantics guidance is present
    assert "Player evidence queries" in prompt
    assert "match_take=N" in prompt
    assert "NO name search" in prompt
    assert "numeric Steam32 id" in prompt
    assert "It is mandatory before player_recent_matches or player_hero_performance" in prompt
    assert "$<profile_call>.data.confirmed_steam_account_id" in prompt


def test_agentic_planner_accepts_player_hero_performance_plan() -> None:
    payload = _player_hero_performance_payload()
    planner = AgentController(
        _registry(), llm=FakeLLM(payload), llm_enabled=True, planner_max_retries=0
    )

    result = asyncio.run(planner.decide("853634884 近 20 场什么英雄胜率高"))

    assert result.status == "decided"
    assert result.errors == []


def test_agentic_planner_rejects_player_plan_with_region_filter() -> None:
    payload = _player_hero_performance_payload()
    payload["plan"]["context"]["region_ids"] = ["CHINA"]
    planner = AgentController(
        _registry(), llm=FakeLLM(payload), llm_enabled=True, planner_max_retries=0
    )

    result = asyncio.run(planner.decide("853634884 国服什么英雄胜率高"))

    # validate_context_scope rejects region_ids on non-hero_daily_trends tools
    assert result.status == "error"
    assert any("region_ids/game_mode_ids" in err for err in result.errors)
