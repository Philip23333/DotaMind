from __future__ import annotations

import asyncio
from typing import Any

from app.vnext.agent.limits import AgentLimits
from app.vnext.agent.runtime import AgentRuntime
from app.vnext.composition import build_vnext_registry
from app.vnext.llm.protocol import (
    AssistantMessage,
    FinalMessage,
    ModelRequest,
    ModelResponse,
    ToolCall,
    ToolResultMessage,
    UserMessage,
)
from tests.vnext.fakes import ScriptedTranscriptModelClient
from tests.vnext.phase2_support import fixture_services, fixture_vnext_services


def _runtime():
    series_service, match_service, panda, opendota = fixture_services()
    services = fixture_vnext_services(series_service, match_service, panda, opendota)
    registry = build_vnext_registry(services)
    runtime = AgentRuntime(
        ScriptedTranscriptModelClient([]),
        registry,
        limits=AgentLimits(deadline_seconds=2),
    )
    return runtime, services, registry


def _last_tool_result(request: ModelRequest) -> dict[str, Any]:
    for message in reversed(request.messages):
        if isinstance(message, ToolResultMessage):
            assert message.status == "ok"
            assert isinstance(message.content, dict)
            return message.content
    raise AssertionError("scripted model expected a preceding tool result")


def _assistant_call(call: ToolCall) -> ModelResponse:
    return ModelResponse.from_assistant(
        AssistantMessage(content=None, tool_calls=[call])
    )


def _tool_calls(model: ScriptedTranscriptModelClient) -> list[ToolCall]:
    return [
        message.message.tool_calls[0]
        for message in model.responses
        if isinstance(message.message, AssistantMessage) and message.message.tool_calls
    ]


def test_behavior_scenario_a_series_search_runs_through_runtime_and_registry() -> None:
    runtime, _, registry = _runtime()
    model = ScriptedTranscriptModelClient(
        [
            lambda request: _assistant_call(
                ToolCall(
                    id="series-search",
                    name="series.search",
                    arguments={"query": "The International 2026", "year": 2026},
                )
            ),
            lambda request: ModelResponse.from_final("赛事已找到"),
        ]
    )
    runtime.model = model

    final = asyncio.run(runtime.run([UserMessage(content="帮我查一下 The International 2026")]))

    assert final == FinalMessage(content="赛事已找到")
    assert _tool_calls(model)[0].name == "series.search"
    assert [tool.name for tool in registry.list()] == [
        "series.search",
        "series.list_matches",
        "matches.search",
        "matches.get_detail",
        "teams.search",
        "teams.get_detail",
        "players.search",
        "players.get_detail",
        "artifact.search",
        "artifact.grep",
        "artifact.read",
    ]
    assert len(model.requests[0].tools) == 11


def test_behavior_scenario_b_upcoming_uses_series_ref_from_prior_tool_result() -> None:
    runtime, _, _ = _runtime()
    model = ScriptedTranscriptModelClient(
        [
            lambda request: _assistant_call(
                ToolCall(
                    id="series-search",
                    name="series.search",
                    arguments={"query": "The International 2026", "year": 2026},
                )
            ),
            lambda request: _assistant_call(
                ToolCall(
                    id="series-matches",
                    name="series.list_matches",
                    arguments={
                        "series_ref": {
                            "value": _last_tool_result(request)["candidates"][0]["ref"]["value"]
                        },
                        "time_scope": "upcoming",
                    },
                )
            ),
            lambda request: ModelResponse.from_final("下一场已找到"),
        ]
    )
    runtime.model = model

    final = asyncio.run(runtime.run([UserMessage(content="下一场什么时候？")]))

    assert final.content == "下一场已找到"
    calls = _tool_calls(model)
    assert [call.name for call in calls] == [
        "series.search",
        "series.list_matches",
    ]
    assert calls[1].arguments["series_ref"]["value"].startswith("series:")
    assert calls[1].arguments["time_scope"] == "upcoming"


def test_behavior_scenario_c_team_search_and_match_detail_use_runtime_tool_calls() -> None:
    runtime, _, _ = _runtime()
    model = ScriptedTranscriptModelClient(
        [
            lambda request: _assistant_call(
                ToolCall(
                    id="match-search",
                    name="matches.search",
                    arguments={
                        "teams": ["Team Alpha", "Team Beta"],
                        "time_scope": "recent",
                    },
                )
            ),
            lambda request: _assistant_call(
                ToolCall(
                    id="match-detail",
                    name="matches.get_detail",
                    arguments={
                        "match_ref": {
                            "value": _last_tool_result(request)["candidates"][0]["ref"]["value"]
                        }
                    },
                )
            ),
            lambda request: ModelResponse.from_final("这场比赛详情已返回"),
        ]
    )
    runtime.model = model

    final = asyncio.run(
        runtime.run([UserMessage(content="Team Alpha 和 Team Beta 最近一次交手？")])
    )

    assert final.content == "这场比赛详情已返回"
    calls = _tool_calls(model)
    assert [call.name for call in calls] == ["matches.search", "matches.get_detail"]
    assert calls[1].arguments["match_ref"]["value"].startswith("match:")


def test_behavior_scenario_d_second_game_uses_exact_game_ref_through_runtime() -> None:
    runtime, services, _ = _runtime()
    model = ScriptedTranscriptModelClient(
        [
            lambda request: _assistant_call(
                ToolCall(
                    id="match-search",
                    name="matches.search",
                    arguments={"query": "Grand Final", "time_scope": "recent"},
                )
            ),
            lambda request: _assistant_call(
                ToolCall(
                    id="match-detail",
                    name="matches.get_detail",
                    arguments={
                        "match_ref": {
                            "value": _last_tool_result(request)["candidates"][0]["ref"]["value"]
                        }
                    },
                )
            ),
            lambda request: _assistant_call(
                ToolCall(
                    id="game-detail",
                    name="matches.get_detail",
                    arguments={
                        "game_ref": {
                            "value": next(
                                game["ref"]["value"]
                                for game in _last_tool_result(request)["games"]
                                if game["position"] == 2
                            )
                        }
                    },
                )
            ),
            lambda request: ModelResponse.from_final("第二局是 Team Beta 获胜"),
        ]
    )
    runtime.model = model

    final = asyncio.run(runtime.run([UserMessage(content="第二局详细说说")]))

    assert final.content == "第二局是 Team Beta 获胜"
    assert services.opendota.detail_calls == [40002, 40003, 40004, 40003]
    calls = _tool_calls(model)
    assert [call.name for call in calls] == [
        "matches.search",
        "matches.get_detail",
        "matches.get_detail",
    ]
    assert "match_ref" not in calls[-1].arguments
    assert calls[-1].arguments["game_ref"]["value"].startswith("game:")
