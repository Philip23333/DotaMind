import asyncio
from typing import Any

from app.agentic.planning.planner import AgenticPlanner
from app.agentic.tools.stratz_tools import build_default_tool_registry
from app.core.config import Settings
from app.llm.provider import LLMJSONDecodeError, ToolCallResult


class FakeLLM:
    """Test double for the planner LLM.

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
        if self._error is not None:
            raise self._error
        if self._sequence is not None:
            if self._index >= len(self._sequence):
                raise AssertionError("FakeLLM sequence exhausted")
            item = self._sequence[self._index]
            self._index += 1
            if isinstance(item, Exception):
                raise item
            return item
        assert self._single is not None
        return self._single

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
        "reason": "matchup ranking can be answered with registered tools",
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


def test_agentic_planner_accepts_valid_counter_pick_plan() -> None:
    planner = AgenticPlanner(_registry(), llm=FakeLLM(_valid_plan_payload()), llm_enabled=True, planner_max_retries=0)

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
        planner_max_retries=0,
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
    planner = AgenticPlanner(_registry(), llm=FakeLLM(payload), llm_enabled=True, planner_max_retries=0)

    result = asyncio.run(planner.plan("How Team BB play lately?"))

    assert result.status == "error"
    assert "unknown tool" in result.errors[0]
    assert result.raw_output == payload


def test_agentic_planner_accepts_hardcoded_hero_id_when_schema_allows_int() -> None:
    payload = _valid_plan_payload()
    payload["plan"]["tool_calls"][1]["args"]["hero_id"] = 25
    planner = AgenticPlanner(_registry(), llm=FakeLLM(payload), llm_enabled=True, planner_max_retries=0)

    result = asyncio.run(planner.plan("enemy picked Lina, what should I pick?"))

    assert result.status == "planned"


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
        "pair_lane_winrate",
        "sample_size",
    ]
    planner = AgenticPlanner(_registry(), llm=FakeLLM(payload), llm_enabled=True, planner_max_retries=0)

    result = asyncio.run(planner.plan("how does SK + AA lane?"))

    assert result.status == "planned"


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
        "pair_lane_winrate",
        "sample_size",
    ]
    planner = AgenticPlanner(_registry(), llm=FakeLLM(payload), llm_enabled=True, planner_max_retries=0)

    result = asyncio.run(planner.plan("how does SK + AA lane?"))

    assert result.status == "error"
    assert any("stratz.pair_lane_outcome invalid args" in item for item in result.errors)


def test_agentic_planner_rejects_mock_allowed() -> None:
    payload = _valid_plan_payload()
    payload["plan"]["constraints"]["allow_mock"] = True
    planner = AgenticPlanner(_registry(), llm=FakeLLM(payload), llm_enabled=True, planner_max_retries=0)

    result = asyncio.run(planner.plan("enemy picked Lina, what should I pick?"))

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
    planner = AgenticPlanner(_registry(), llm=FakeLLM(payload), llm_enabled=True, planner_max_retries=0)

    result = asyncio.run(planner.plan("what changed in 7.41d?"))

    assert result.status == "error"
    assert "missing required evidence" in " ".join(result.errors)


def test_agentic_planner_rejects_matchup_tool_results_contract() -> None:
    payload = _valid_plan_payload()
    payload["plan"]["output_contract"] = "tool_results"
    planner = AgenticPlanner(_registry(), llm=FakeLLM(payload), llm_enabled=True, planner_max_retries=0)

    result = asyncio.run(planner.plan("enemy picked Lina, what should I pick?"))

    assert result.status == "error"
    assert "unknown output_contract: tool_results" in " ".join(result.errors)


def test_agentic_planner_rejects_meta_list_contract() -> None:
    payload = _valid_plan_payload()
    payload["plan"]["output_contract"] = "meta_list"
    planner = AgenticPlanner(_registry(), llm=FakeLLM(payload), llm_enabled=True, planner_max_retries=0)

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
    planner = AgenticPlanner(_registry(), llm=FakeLLM(payload), llm_enabled=True, planner_max_retries=0)

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
    planner = AgenticPlanner(_registry(), llm=FakeLLM(payload), llm_enabled=True, planner_max_retries=0)

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
    planner = AgenticPlanner(_registry(), llm=FakeLLM(payload), llm_enabled=True, planner_max_retries=0)

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
    planner = AgenticPlanner(_registry(), llm=FakeLLM(_valid_plan_payload()), llm_enabled=True, planner_max_retries=0)

    prompt = planner._system_prompt()

    assert "team_recent_report" in prompt
    assert "recent_matches" in prompt
    assert "current_players" in prompt
    assert "team_hero_usage" in prompt
    assert "evidence_produced" in prompt
    assert "allowed_arg_keys" in prompt
    assert "Do not invent aliases or synonyms" in prompt
    assert "recent_matches, do not" in prompt
    assert "- is_with: bool, required" in prompt
    assert "$<previous_call_id>.data.hero.hero_id" in prompt
    assert "DIVINE_IMMORTAL" in prompt
    assert "Map 冠绝/Immortal/Divine to DIVINE_IMMORTAL" in prompt
    assert "$resolve_target.data.hero.hero_id" not in prompt
    # Slimmed: redundant meta-rule markers and the inline example are gone.
    assert "produced_evidence_names_must_be_exact" not in prompt
    assert "required_evidence_names_must_be_exact" not in prompt
    assert '"matches": "$get_matches.data.matches"' not in prompt


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
    planner = AgenticPlanner(_registry(), llm=FakeLLM(payload), llm_enabled=True, planner_max_retries=0)

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
    planner = AgenticPlanner(_registry(), llm=FakeLLM(payload), llm_enabled=True, planner_max_retries=0)

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
    planner = AgenticPlanner(_registry(), llm=FakeLLM(payload), llm_enabled=True, planner_max_retries=0)

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
    planner = AgenticPlanner(_registry(), llm=FakeLLM(payload), llm_enabled=True, planner_max_retries=0)

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
    planner = AgenticPlanner(_registry(), llm=FakeLLM(payload), llm_enabled=True, planner_max_retries=0)

    result = asyncio.run(planner.plan("latest patch impact?"))

    assert result.status == "error"
    assert "patch_records" in result.errors[0]


def test_agentic_planner_returns_error_when_disabled() -> None:
    planner = AgenticPlanner(_registry(), llm=FakeLLM(_valid_plan_payload()), llm_enabled=False)

    result = asyncio.run(planner.plan("enemy picked Lina, what should I pick?"))

    assert result.status == "error"
    assert "LLM planner is disabled" in result.reason


def test_agentic_planner_retries_on_validation_error_then_succeeds() -> None:
    bad_payload = _valid_plan_payload()
    bad_payload["plan"]["required_evidence"] = [
        "hero_identity",
        "matchup_ranking_row",
        "hero_name",  # unknown evidence kind -> validation rejects
    ]
    good_payload = _valid_plan_payload()
    planner = AgenticPlanner(
        _registry(),
        llm=FakeLLM([bad_payload, good_payload]),
        llm_enabled=True,
        planner_max_retries=2,
    )

    result = asyncio.run(planner.plan("enemy picked Lina, what should I pick?"))

    assert result.status == "planned"
    assert result.plan is not None
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
    planner = AgenticPlanner(
        _registry(),
        llm=FakeLLM([shape_error_payload, good_payload]),
        llm_enabled=True,
        planner_max_retries=2,
    )

    result = asyncio.run(planner.plan("enemy picked Lina, what should I pick?"))

    assert result.status == "planned"
    assert [message["role"] for message in result.prompt_messages] == [
        "system",
        "user",
        "assistant",
        "user",
    ]


def test_agentic_planner_exhausts_retries_and_returns_error() -> None:
    bad_payload = _valid_plan_payload()
    bad_payload["plan"]["required_evidence"] = ["hero_identity", "hero_name"]
    planner = AgenticPlanner(
        _registry(),
        llm=FakeLLM(bad_payload),
        llm_enabled=True,
        planner_max_retries=2,
    )

    result = asyncio.run(planner.plan("enemy picked Lina, what should I pick?"))

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
    planner = AgenticPlanner(
        _registry(),
        llm=FakeLLM(bad_payload),
        llm_enabled=True,
        planner_max_retries=0,
    )

    result = asyncio.run(planner.plan("enemy picked Lina, what should I pick?"))

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
    planner = AgenticPlanner(
        _registry(), llm=FakeLLM(_matchup_payload()), llm_enabled=True, planner_max_retries=0
    )

    result = asyncio.run(planner.plan("enemy picked Lina, what should I pick?"))

    assert result.status == "planned"
    assert result.plan.tool_calls[1].args["min_sample_size"] == 2000
    applied = result.plan.metadata["policy_applied"]
    assert [r["tool_call_id"] for r in applied] == ["get_ranking"]
    assert applied[0]["mode"] == "default"


def test_agentic_planner_preserves_explicit_relaxed_sample_size() -> None:
    # "冷门也行" -> LLM chose relaxed (500). Preserved, no provenance.
    planner = AgenticPlanner(
        _registry(), llm=FakeLLM(_matchup_payload(500)), llm_enabled=True, planner_max_retries=0
    )

    result = asyncio.run(planner.plan("Lina 克制谁？冷门也行"))

    assert result.status == "planned"
    assert result.plan.tool_calls[1].args["min_sample_size"] == 500
    assert result.plan.metadata.get("policy_applied") is None


def test_agentic_planner_preserves_explicit_strict_sample_size() -> None:
    # "稳健" -> LLM chose strict (5000). Preserved, no provenance.
    planner = AgenticPlanner(
        _registry(), llm=FakeLLM(_matchup_payload(5000)), llm_enabled=True, planner_max_retries=0
    )

    result = asyncio.run(planner.plan("Lina 克制谁？要稳健大样本"))

    assert result.status == "planned"
    assert result.plan.tool_calls[1].args["min_sample_size"] == 5000
    assert result.plan.metadata.get("policy_applied") is None


def test_agentic_planner_preserves_explicit_user_named_sample_size() -> None:
    # "至少 3000 场" -> explicit (3000), overriding policy tiers. Preserved.
    planner = AgenticPlanner(
        _registry(), llm=FakeLLM(_matchup_payload(3000)), llm_enabled=True, planner_max_retries=0
    )

    result = asyncio.run(planner.plan("Lina 克制谁？至少 3000 场样本"))

    assert result.status == "planned"
    assert result.plan.tool_calls[1].args["min_sample_size"] == 3000
    assert result.plan.metadata.get("policy_applied") is None


def test_agentic_planner_treats_null_sample_size_as_omitted() -> None:
    # LLM emitted JSON null — without backfill validate would reject it as
    # not-an-int. Post-process converts null -> default and records provenance.
    planner = AgenticPlanner(
        _registry(), llm=FakeLLM(_matchup_payload(None)), llm_enabled=True, planner_max_retries=0
    )

    result = asyncio.run(planner.plan("enemy picked Lina, what should I pick?"))

    assert result.status == "planned"
    assert result.plan.tool_calls[1].args["min_sample_size"] == 2000
    applied = result.plan.metadata["policy_applied"]
    assert [r["tool_call_id"] for r in applied] == ["get_ranking"]


def test_agentic_planner_prompt_contains_sample_policy_table() -> None:
    planner = AgenticPlanner(
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
                    "id": "heroperf",
                    "tool": "stratz.player_hero_performance",
                    "args": {
                        "steam_account_id": 853634884,
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
    planner = AgenticPlanner(
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


def test_agentic_planner_accepts_player_hero_performance_plan() -> None:
    payload = _player_hero_performance_payload()
    planner = AgenticPlanner(
        _registry(), llm=FakeLLM(payload), llm_enabled=True, planner_max_retries=0
    )

    result = asyncio.run(planner.plan("853634884 近 20 场什么英雄胜率高"))

    assert result.status == "planned"
    assert result.errors == []


def test_agentic_planner_rejects_player_plan_with_region_filter() -> None:
    payload = _player_hero_performance_payload()
    payload["plan"]["context"]["region_ids"] = ["CHINA"]
    planner = AgenticPlanner(
        _registry(), llm=FakeLLM(payload), llm_enabled=True, planner_max_retries=0
    )

    result = asyncio.run(planner.plan("853634884 国服什么英雄胜率高"))

    # validate_context_scope rejects region_ids on non-hero_daily_trends tools
    assert result.status == "error"
    assert any("region_ids/game_mode_ids" in err for err in result.errors)
