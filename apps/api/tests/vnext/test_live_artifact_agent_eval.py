"""Opt-in live full-chain evaluation for the production vNext composition."""

from __future__ import annotations

import asyncio
import json
import os
from typing import Any

import pytest

from app.vnext.agent.runtime import AgentRuntime
from app.vnext.artifacts.game_summary_v4 import GameSummaryArtifactV4
from app.vnext.artifacts.models import game_summary_artifact_ref
from app.vnext.composition import (
    VNextSettings,
    build_vnext_runtime,
    build_vnext_services,
)
from app.vnext.llm.protocol import ToolCall, ToolResultMessage
from scripts.vnext_agent_console import (
    _run_turn,
    _tool_calls,
    _tool_results,
    _trace_rows,
    _TracingModelClient,
)

if os.getenv("DOTAMIND_LIVE_AGENT_EVAL") != "1":
    pytest.skip(
        "live agent eval disabled; set DOTAMIND_LIVE_AGENT_EVAL=1",
        allow_module_level=True,
    )


MATCH_PROMPT = "查询 The International 2026 的总决赛，告诉我比赛双方和最终结果。"
ARTIFACT_PROMPT = "再看总决赛最后一局，Yatoro 用了什么英雄，最终装备是什么？"


def _failure_context(
    phase: str,
    prompt: str,
    calls: list[ToolCall],
    results: list[ToolResultMessage],
    *,
    answer: str | None = None,
    trace_path: object | None = None,
) -> str:
    return (
        f"{phase}: prompt={prompt!r}; answer={answer!r}; trace_path={trace_path!r}; "
        f"compact_trace={json.dumps(_trace_rows(calls, results, []), ensure_ascii=False)}"
    )


def _result_map(results: list[ToolResultMessage]) -> dict[str, ToolResultMessage]:
    return {result.tool_call_id: result for result in results}


def _call_result(
    call: ToolCall,
    results: dict[str, ToolResultMessage],
) -> ToolResultMessage | None:
    return results.get(call.id)


def _result_content(result: ToolResultMessage | None) -> dict[str, Any] | None:
    if result is None or result.status != "ok" or not isinstance(result.content, dict):
        return None
    return result.content


def _has_match_data(content: dict[str, Any]) -> bool:
    return any(
        isinstance(content.get(key), list) and bool(content[key])
        for key in ("matches", "candidates", "games")
    ) or isinstance(content.get("match"), dict)


def _resolved_game_rows(
    calls: list[ToolCall],
    results: dict[str, ToolResultMessage],
) -> list[tuple[int | None, int]]:
    rows: list[tuple[int | None, int]] = []
    for call in calls:
        if call.name != "matches.get_detail":
            continue
        content = _result_content(_call_result(call, results))
        if content is None:
            continue
        games = content.get("games")
        if not isinstance(games, list):
            continue
        for game in games:
            if not isinstance(game, dict):
                continue
            valve_match_id = game.get("valve_match_id")
            if isinstance(valve_match_id, int) and not isinstance(valve_match_id, bool):
                position = game.get("position")
                rows.append((position if isinstance(position, int) else None, valve_match_id))
    return rows


def _is_yatoro(player: Any) -> bool:
    return _yatoro_name(player) is not None


def _yatoro_name(player: Any) -> str | None:
    identity = getattr(player, "identity", None)
    if identity is None:
        return None
    for name in (identity.registered_name, identity.persona_name):
        if isinstance(name, str) and name and name.casefold() == "yatoro":
            return name
    return None


def _successful_artifact_read_values(
    calls: list[ToolCall],
    results: dict[str, ToolResultMessage],
) -> list[Any]:
    values: list[Any] = []
    for call in calls:
        if call.name != "artifact.read":
            continue
        content = _result_content(_call_result(call, results))
        if content is not None:
            values.append(content.get("value"))
    return values


def _contains_value(value: object, payload: Any) -> bool:
    if payload == value:
        return True
    if isinstance(payload, dict):
        return any(_contains_value(value, child) for child in payload.values())
    if isinstance(payload, list):
        return any(_contains_value(value, child) for child in payload)
    return False


def _answer_contains(answer: str, value: str) -> bool:
    return value.casefold() in answer.casefold()


def _live_settings() -> VNextSettings:
    settings = VNextSettings.from_env()
    if not settings.llm_api_key:
        pytest.skip("live agent eval skipped; LLM API key is not configured")
    if not settings.pandascore_token:
        pytest.skip("live agent eval skipped; PandaScore token is not configured")
    return settings


async def _run_live_full_chain(settings: VNextSettings) -> None:
    services = build_vnext_services(settings)
    base_runtime = build_vnext_runtime(settings, services=services)
    model = _TracingModelClient(base_runtime.model)
    runtime = AgentRuntime(model, base_runtime.tools, limits=base_runtime.limits)

    try:
        first_response_start = len(model.responses)
        first_request_start = len(model.requests)
        first_final, history, first_trace_path, first_error = await _run_turn(
            runtime,
            model,
            [],
            MATCH_PROMPT,
            "live_full_chain_match",
        )
        first_calls = _tool_calls(model, start=first_response_start)
        first_results = _tool_results(model, start=first_request_start)
        first_result_map = _result_map(first_results)
        first_context = _failure_context(
            "discovery",
            MATCH_PROMPT,
            first_calls,
            first_results,
            answer=first_final.content if first_final is not None else None,
            trace_path=first_trace_path,
        )

        assert first_error is None and first_final is not None, (
            "first turn did not reach terminal final: "
            f"{type(first_error).__name__ if first_error else 'missing final'}; {first_context}"
        )
        assert len(model.responses) - first_response_start <= runtime.limits.max_steps, (
            f"first turn exceeded max_steps; {first_context}"
        )
        assert len(first_calls) <= runtime.limits.max_tool_calls, (
            f"first turn exceeded max_tool_calls; {first_context}"
        )
        assert all(result.status == "ok" for result in first_results), (
            f"first turn returned a tool error; {first_context}"
        )

        competition_calls = [
            call for call in first_calls if call.name == "competitions.search"
        ]
        assert competition_calls, f"discovery did not call competitions.search; {first_context}"
        competition_contents = [
            content
            for call in competition_calls
            if (content := _result_content(_call_result(call, first_result_map))) is not None
        ]
        assert any(content.get("candidates") for content in competition_contents), (
            f"discovery returned no competition candidates; {first_context}"
        )
        assert any(
            _has_match_data(content)
            for result in first_results
            if (content := _result_content(result)) is not None
        ), f"discovery returned no match data after competition search; {first_context}"

        second_response_start = len(model.responses)
        second_request_start = len(model.requests)
        second_final, _second_history, second_trace_path, second_error = await _run_turn(
            runtime,
            model,
            history,
            ARTIFACT_PROMPT,
            "live_full_chain_artifact",
        )
        second_calls = _tool_calls(model, start=second_response_start)
        second_results = [
            result
            for result in _tool_results(model, start=second_request_start)
            if result.tool_call_id in {call.id for call in second_calls}
        ]
        second_result_map = _result_map(second_results)
        second_context = _failure_context(
            "retrieval",
            ARTIFACT_PROMPT,
            second_calls,
            second_results,
            answer=second_final.content if second_final is not None else None,
            trace_path=second_trace_path,
        )

        assert second_error is None and second_final is not None, (
            "second turn did not reach terminal final: "
            f"{type(second_error).__name__ if second_error else 'missing final'}; {second_context}"
        )
        assert len(model.responses) - second_response_start <= runtime.limits.max_steps, (
            f"second turn exceeded max_steps; {second_context}"
        )
        assert len(second_calls) <= runtime.limits.max_tool_calls, (
            f"second turn exceeded max_tool_calls; {second_context}"
        )
        detail_calls = [
            call for call in second_calls if call.name == "matches.get_detail"
        ]
        assert detail_calls, f"resolution did not call matches.get_detail; {second_context}"
        resolved_games = _resolved_game_rows(second_calls, second_result_map)
        assert resolved_games, (
            "resolution did not return a resolved valve_match_id from matches.get_detail; "
            f"{second_context}"
        )
        read_calls = [call for call in second_calls if call.name == "artifact.read"]
        assert read_calls, f"retrieval did not call artifact.read; {second_context}"
        assert all(result.status == "ok" for result in second_results), (
            f"second turn returned a tool error; {second_context}"
        )

        positioned_games = [row for row in resolved_games if row[0] is not None]
        _position, valve_match_id = max(
            positioned_games or resolved_games,
            key=lambda row: row[0] if row[0] is not None else -1,
        )
        artifact_ref = game_summary_artifact_ref(valve_match_id)
        assert await services.artifact_store.exists(artifact_ref), (
            "production did not store the resolved game artifact; "
            f"{second_context}; ref={artifact_ref.model_dump(mode='json')}"
        )
        try:
            artifact = await services.artifact_store.get(artifact_ref)
        except Exception as exc:
            pytest.fail(
                "production could not retrieve the stored artifact: "
                f"{type(exc).__name__}: {exc}; {second_context}"
            )
        assert isinstance(artifact, GameSummaryArtifactV4), (
            f"production stored an unexpected artifact type; {second_context}"
        )
        assert artifact.schema_version == "4", (
            f"production stored the wrong artifact schema version; {second_context}"
        )

        yatoro_players = [player for player in artifact.players if _is_yatoro(player)]
        assert len(yatoro_players) == 1, (
            f"grounding could not identify exactly one Yatoro player; {second_context}"
        )
        yatoro = yatoro_players[0]
        yatoro_name = _yatoro_name(yatoro)
        assert yatoro_name is not None, f"grounding found no Yatoro name; {second_context}"
        assert yatoro.hero.name, f"grounding found no resolved Yatoro hero; {second_context}"
        inventory_names = [
            item.name
            for item in yatoro.items.inventory
            if isinstance(item.name, str) and item.name.strip()
        ]
        assert inventory_names, f"grounding found no non-empty final inventory; {second_context}"

        read_values = _successful_artifact_read_values(second_calls, second_result_map)
        expected_facts = [yatoro_name, yatoro.hero.name, *inventory_names]
        for fact in expected_facts:
            assert any(_contains_value(fact, value) for value in read_values), (
                f"grounding artifact.read result omitted fact {fact!r}; {second_context}"
            )
            assert _answer_contains(second_final.content, fact), (
                f"grounding final answer omitted fact {fact!r}; {second_context}"
            )
    finally:
        await services.aclose()


@pytest.mark.live_agent_eval
def test_live_full_chain_artifact_agent_eval() -> None:
    asyncio.run(_run_live_full_chain(_live_settings()))
