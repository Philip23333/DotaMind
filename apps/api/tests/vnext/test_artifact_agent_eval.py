"""Opt-in real-model evaluations for fixture-backed artifact retrieval behavior."""

from __future__ import annotations

import asyncio
import json
import os
import re
from typing import Any

import pytest

from app.integrations.valve.catalog_repository import load_default_catalog_repository
from app.vnext.agent.limits import AgentLimits
from app.vnext.agent.runtime import AgentRuntime
from app.vnext.artifacts.game_summary_builder import GameSummaryBuilder
from app.vnext.composition import build_vnext_registry
from app.vnext.identity import AbilityResolver, HeroResolver, ItemResolver
from app.vnext.llm.openai_compatible import OpenAICompatibleModelClient
from app.vnext.llm.protocol import (
    AssistantMessage,
    ModelRequest,
    ModelResponse,
    ToolCall,
    ToolResultMessage,
    UserMessage,
)
from tests.vnext.phase2_support import fixture_services, fixture_vnext_services


class _TracingModelClient:
    """Capture compact test evidence while delegating every response to a real model."""

    def __init__(self, client: OpenAICompatibleModelClient) -> None:
        self._client = client
        self.requests: list[ModelRequest] = []
        self.responses: list[ModelResponse] = []

    async def complete(self, request: ModelRequest) -> ModelResponse:
        self.requests.append(request.model_copy(deep=True))
        response = await self._client.complete(request)
        self.responses.append(response.model_copy(deep=True))
        return response


def _build_real_model() -> OpenAICompatibleModelClient:
    base_url = os.getenv("DOTAMIND_AGENT_EVAL_BASE_URL")
    model = os.getenv("DOTAMIND_AGENT_EVAL_MODEL")
    if not base_url or not model:
        pytest.skip(
            "agent_eval requires DOTAMIND_AGENT_EVAL_BASE_URL and DOTAMIND_AGENT_EVAL_MODEL"
        )
    return OpenAICompatibleModelClient(
        api_key=os.getenv("DOTAMIND_AGENT_EVAL_API_KEY", ""),
        base_url=base_url,
        model=model,
    )


def _fixture_builder() -> GameSummaryBuilder:
    catalog = load_default_catalog_repository()
    return GameSummaryBuilder(
        hero_resolver=HeroResolver(catalog.hero_name_index()),
        item_resolver=ItemResolver(
            {item.item_id: item.name_en for item in catalog.list_items()},
            item_key_to_id=catalog.item_key_index(),
        ),
        ability_resolver=AbilityResolver(catalog.ability_name_index()),
    )


def _build_eval_runtime() -> tuple[AgentRuntime, _TracingModelClient]:
    competition_service, match_service, panda, opendota = fixture_services()
    services = fixture_vnext_services(
        competition_service,
        match_service,
        panda,
        opendota,
        builder=_fixture_builder(),
    )
    model = _TracingModelClient(_build_real_model())
    return AgentRuntime(model, build_vnext_registry(services)), model


def _fixture_facts() -> dict[str, Any]:
    """Derive every hard assertion from the canonical artifact used by the eval."""

    competition_service, match_service, panda, opendota = fixture_services()
    services = fixture_vnext_services(
        competition_service,
        match_service,
        panda,
        opendota,
        builder=_fixture_builder(),
    )
    ref = asyncio.run(services.game_summary_producer.produce(40003))
    artifact = services.artifact_store.get(ref)
    player = next(item for item in artifact.players if item.identity.registered_name == "carry")
    item_names = [item.name for item in player.items.inventory if item.name is not None]
    ability_names = [
        upgrade.ability_name
        for upgrade in player.ability_upgrades
        if upgrade.ability_name is not None
    ]

    assert item_names == ["Blink Dagger", "Phase Boots"]
    assert ability_names == ["Mana Break", "Blink"]
    assert player.economy.net_worth == 18500
    assert player.economy.gold_per_min == 620

    return {
        "player_name": player.identity.registered_name,
        "item_names": item_names,
        "ability_names": ability_names,
        "net_worth": player.economy.net_worth,
        "gold_per_min": player.economy.gold_per_min,
    }


def _tool_calls(model: _TracingModelClient) -> list[ToolCall]:
    return [
        call
        for response in model.responses
        if isinstance(response.message, AssistantMessage)
        for call in response.message.tool_calls
    ]


def _tool_results(model: _TracingModelClient) -> list[ToolResultMessage]:
    results: list[ToolResultMessage] = []
    seen_ids: set[str] = set()
    for request in model.requests:
        for message in request.messages:
            if isinstance(message, ToolResultMessage) and message.tool_call_id not in seen_ids:
                seen_ids.add(message.tool_call_id)
                results.append(message)
    return results


def _compact_trace(calls: list[ToolCall], results: list[ToolResultMessage]) -> str:
    result_by_id = {result.tool_call_id: result for result in results}
    rows: list[dict[str, Any]] = []
    for call in calls:
        result = result_by_id.get(call.id)
        rows.append(
            {
                "tool": call.name,
                "arguments": call.arguments,
                "status": result.status if result else "not_returned",
                "error": result.error.code if result and result.error else None,
            }
        )
    return json.dumps(rows, ensure_ascii=False)


def _failure_context(
    prompt: str,
    answer: str,
    calls: list[ToolCall],
    results: list[ToolResultMessage],
) -> str:
    return f"prompt={prompt!r}\nanswer={answer!r}\ntrace={_compact_trace(calls, results)}"


def _contains_value(value: object, payload: Any) -> bool:
    if payload == value:
        return True
    if isinstance(payload, dict):
        return any(_contains_value(value, child) for child in payload.values())
    if isinstance(payload, list):
        return any(_contains_value(value, child) for child in payload)
    return False


def _successful_artifact_read_contains(
    calls: list[ToolCall],
    results: list[ToolResultMessage],
    value: object,
) -> bool:
    result_by_id = {result.tool_call_id: result for result in results}
    return any(
        call.name == "artifact.read"
        and (result := result_by_id.get(call.id)) is not None
        and result.status == "ok"
        and _contains_value(value, result.content)
        for call in calls
    )


def _contains_recorded_number(answer: str, value: int) -> bool:
    return str(value) in re.sub(r"[,\s]", "", answer)


@pytest.mark.agent_eval
def test_artifact_agent_eval_deep_facts_and_follow_up() -> None:
    runtime, model = _build_eval_runtime()
    facts = _fixture_facts()
    prompt = (
        "请找 Grand Final 的第二局，概述 carry 的最终装备、购买记录和技能加点；"
        "装备和技能请保留工具结果中的英文名称。"
    )

    first_final = asyncio.run(runtime.run([UserMessage(content=prompt)]))
    first_calls = _tool_calls(model)
    first_results = _tool_results(model)
    first_context = _failure_context(prompt, first_final.content, first_calls, first_results)

    assert len(first_calls) <= AgentLimits().max_tool_calls, first_context
    assert any(
        call.name == "artifact.read" for call in first_calls
    ), first_context
    for fact in [*facts["item_names"], *facts["ability_names"]]:
        assert _successful_artifact_read_contains(first_calls, first_results, fact), first_context
        assert fact in first_final.content, first_context
    for conflicting_fact in ("Black King Bar", "Counterspell"):
        assert conflicting_fact not in first_final.content, first_context
    for provider_private_id in ("30004", "72002", "70010", "70011"):
        assert provider_private_id not in first_final.content, first_context

    follow_up_prompt = "那他这局经济情况怎么样？请给出记录中的净资产和每分钟金币。"
    follow_up_messages = [
        *model.requests[-1].messages,
        first_final,
        UserMessage(content=follow_up_prompt),
    ]
    second_final = asyncio.run(runtime.run(follow_up_messages))
    all_calls = _tool_calls(model)
    all_results = _tool_results(model)
    second_calls = all_calls[len(first_calls) :]
    second_results = all_results[len(first_results) :]
    second_context = _failure_context(
        follow_up_prompt,
        second_final.content,
        second_calls,
        second_results,
    )

    assert len(second_calls) <= AgentLimits().max_tool_calls, second_context
    assert not any(call.name == "matches.search" for call in second_calls), second_context
    assert _contains_recorded_number(second_final.content, facts["net_worth"]), second_context
    assert _contains_recorded_number(second_final.content, facts["gold_per_min"]), second_context
    assert any(call.name in {"artifact.search", "artifact.read"} for call in second_calls) or (
        _successful_artifact_read_contains(first_calls, first_results, facts["net_worth"])
    ), second_context


@pytest.mark.agent_eval
def test_artifact_agent_eval_missing_data_stays_grounded() -> None:
    runtime, model = _build_eval_runtime()
    prompt = (
        "Grand Final 的第二局里，carry 第一次插眼是什么时间？"
        "如果记录没有这个事实，请明确说无法确认。"
    )

    final = asyncio.run(runtime.run([UserMessage(content=prompt)]))
    calls = _tool_calls(model)
    results = _tool_results(model)
    context = _failure_context(prompt, final.content, calls, results)

    assert len(calls) <= AgentLimits().max_tool_calls, context
    assert any(call.name == "artifact.read" for call in calls), context
    unavailable_markers = (
        "无法确认",
        "无法确定",
        "没有记录",
        "未记录",
        "不可用",
        "cannot determine",
        "not available",
        "unavailable",
    )
    assert any(marker in final.content.casefold() for marker in unavailable_markers), context
    for hallucinated_fact in ("第12分钟插眼", "12 分钟插眼", "720 秒插眼"):
        assert hallucinated_fact not in final.content, context

    retrieval_errors = {
        "artifact_not_found",
        "artifact_path_not_found",
        "artifact_type_mismatch",
    }
    errors = [result.error.code for result in results if result.error is not None]
    assert all(error in retrieval_errors for error in errors), context
