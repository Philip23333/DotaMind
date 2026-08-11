from __future__ import annotations

import asyncio
from typing import Any

import pytest

from app.agentic.answer import AnswerSynthesizer
from app.agentic.graph import AgentGraphRunner
from app.agentic.models import ExecutionPlan, ToolCall
from app.agentic.planning.controller import AgentControllerResult
from app.agentic.planning.decisions import ToolPlanDecision, resolve_required_evidence
from app.agentic.state import AgentRunState
from app.agentic.tools.stratz_tools import build_default_tool_registry
from app.core.config import Settings
from app.integrations.valve.datafeed import ValveDatafeedClient
from app.llm.provider import ToolCallResult


class CatalogController:
    def __init__(self, plan: ExecutionPlan, registry) -> None:
        self.plan = plan
        self.registry = registry

    @property
    def prompt_versions(self) -> dict[str, str]:
        return {}

    async def decide(
        self,
        query: str,
        game: str = "dota2",
        history=None,
        recovery_feedback=None,
        recovery_baseline_decision=None,
        **kwargs,
    ) -> AgentControllerResult:
        return AgentControllerResult(
            status="decided",
            reason="catalog test plan",
            decision=ToolPlanDecision(kind="tool_plan", plan=self.plan),
            evidence_resolution=resolve_required_evidence(self.plan, self.registry),
        )


class CatalogAnswerLLM:
    def __init__(self) -> None:
        self.messages: list[list[dict[str, str]]] = []

    async def complete(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 1000,
    ) -> str:
        self.messages.append([dict(message) for message in messages])
        return "Grounded catalog answer."

    async def complete_json(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 1000,
    ) -> dict[str, Any]:
        raise AssertionError("natural-language answer must use complete, not complete_json")

    async def complete_with_tools(
        self,
        messages: list[dict[str, str]],
        tools: list[dict[str, Any]],
        temperature: float = 0.2,
        max_tokens: int = 1000,
    ) -> ToolCallResult | None:
        return None


class FailingAnswerLLM(CatalogAnswerLLM):
    async def complete(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 1000,
    ) -> str:
        raise RuntimeError("answer unavailable")


class FullAbilityFormattingLLM(CatalogAnswerLLM):
    async def complete(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 1000,
    ) -> str:
        self.messages.append([dict(message) for message in messages])
        assert "'kind': 'hero_ability'" in messages[1]["content"]
        assert "'kind': 'hero_talent_tree'" in messages[1]["content"]
        return (
            "齐天大圣 / Monkey King\n\n"
            "快照：7.41e\n\n"
            "### 棒击大地 / Boundless Strike\n\n"
            "挥出伸长的金箍棒，击晕并伤害直线上的敌人。\n\n"
            "| 等级 | 左侧天赋（中文 / English） | 右侧天赋（中文 / English） |\n"
            "|---|---|---|\n"
            "| 10 | 左侧 / Left | 右侧 / Right |"
        )


@pytest.fixture(autouse=True)
def _forbid_valve_runtime_http(monkeypatch) -> None:
    def fail_fetch(*args, **kwargs):
        raise AssertionError("Catalog Graph runtime must not call Valve HTTP")

    monkeypatch.setattr(ValveDatafeedClient, "fetch", fail_fetch)


def _registry():
    return build_default_tool_registry(
        Settings(
            opendota_base_url="https://api.opendota.test/api",
            stratz_graphql_url="https://api.stratz.test/graphql",
            stratz_token="token",
        )
    )


def _run(plan: ExecutionPlan, *, llm=None):
    registry = _registry()
    answer_llm = llm or CatalogAnswerLLM()
    runner = AgentGraphRunner(CatalogController(plan, registry), registry)
    runner.answer_synthesizer = AnswerSynthesizer(
        llm=answer_llm,
        llm_enabled=True,
    )
    state = asyncio.run(
        runner.run(AgentRunState(query=plan.goal, game="dota2"))
    )
    return state, answer_llm


def _hero_plan(*tools: str) -> ExecutionPlan:
    calls = [ToolCall(id="resolve", tool="resolve_hero", args={"query": "Lina"})]
    evidence = ["hero_identity"]
    mapping = {
        "dota.hero_attributes": ("attributes", "hero_attributes"),
        "dota.hero_abilities": ("abilities", "hero_ability"),
        "dota.hero_talent_tree": ("talents", "hero_talent_tree"),
    }
    for tool in tools:
        call_id, evidence_kind = mapping[tool]
        calls.append(
            ToolCall(
                id=call_id,
                tool=tool,
                args={"hero_id": "$resolve.data.hero.hero_id"},
            )
        )
        evidence.append(evidence_kind)
    return ExecutionPlan(
        intent="catalog_hero_query",
        goal="Answer a static Lina Catalog query.",
        output_contract="natural_language_answer",
        tool_calls=calls,
        required_evidence=evidence,
    )


def _item_plan(query: str, *, recipe: bool) -> ExecutionPlan:
    required = ["item_identity", "item_definition"]
    if recipe:
        required.append("item_recipe")
    return ExecutionPlan(
        intent="catalog_item_query",
        goal=f"Answer a static Catalog query for {query}.",
        output_contract="natural_language_answer",
        tool_calls=[
            ToolCall(id="resolve", tool="resolve_item", args={"query": query}),
            ToolCall(
                id="info",
                tool="dota.item_info",
                args={"item_id": "$resolve.data.item.item_id"},
            ),
        ],
        required_evidence=required,
    )


def _monkey_king_ability_plan(*, complete: bool) -> ExecutionPlan:
    calls = [
        ToolCall(id="resolve", tool="resolve_hero", args={"query": "齐天大圣"}),
        ToolCall(
            id="abilities",
            tool="dota.hero_abilities",
            args={"hero_id": "$resolve.data.hero.hero_id"},
        ),
    ]
    required_evidence = ["hero_identity", "hero_ability"]
    if complete:
        calls.append(
            ToolCall(
                id="talents",
                tool="dota.hero_talent_tree",
                args={"hero_id": "$resolve.data.hero.hero_id"},
            )
        )
        required_evidence.append("hero_talent_tree")
    return ExecutionPlan(
        intent="complete_hero_abilities" if complete else "single_hero_ability",
        goal=(
            "列出齐天大圣的全部技能。"
            if complete
            else "棒击大地是什么，有哪些数值？"
        ),
        output_contract="natural_language_answer",
        tool_calls=calls,
        required_evidence=required_evidence,
    )


@pytest.mark.parametrize(
    ("plan", "expected_kinds"),
    [
        (_hero_plan("dota.hero_attributes"), {"hero_identity", "hero_attributes"}),
        (_hero_plan("dota.hero_abilities"), {"hero_identity", "hero_ability"}),
        (_hero_plan("dota.hero_talent_tree"), {"hero_identity", "hero_talent_tree"}),
        (
            _hero_plan("dota.hero_attributes", "dota.hero_talent_tree"),
            {"hero_identity", "hero_attributes", "hero_talent_tree"},
        ),
        (
            _item_plan("黑皇杖", recipe=True),
            {"item_identity", "item_definition", "item_recipe"},
        ),
        (
            _item_plan("Tome of Knowledge", recipe=False),
            {"item_identity", "item_definition"},
        ),
    ],
)
def test_catalog_graph_success_runs_tool_evidence_answer_and_critic(
    plan: ExecutionPlan,
    expected_kinds: set[str],
) -> None:
    state, llm = _run(plan)

    assert state.status == "ok"
    assert state.evidence_graph is not None
    assert state.evidence_graph.missing == []
    assert {item.kind for item in state.evidence_graph.evidence} == expected_kinds
    assert state.answer is not None
    assert state.answer.status == "ok"
    assert state.answer.summary == "Grounded catalog answer."
    assert state.review is not None
    assert state.review.severity == "pass"
    assert state.response_type == "natural_language_answer"
    assert state.response is not None
    assert isinstance(llm, CatalogAnswerLLM)
    assert len(llm.messages) == 1
    assert all(result.source.kind == "official_snapshot" for result in state.tool_results)


def test_catalog_graph_distinguishes_complete_and_single_ability_evidence() -> None:
    complete_state, _complete_llm = _run(_monkey_king_ability_plan(complete=True))
    single_state, _single_llm = _run(_monkey_king_ability_plan(complete=False))

    assert complete_state.status == "ok"
    assert [result.tool for result in complete_state.tool_results] == [
        "resolve_hero",
        "dota.hero_abilities",
        "dota.hero_talent_tree",
    ]
    assert complete_state.evidence_graph is not None
    assert {
        item.kind for item in complete_state.evidence_graph.evidence
    } == {"hero_identity", "hero_ability", "hero_talent_tree"}

    assert single_state.status == "ok"
    assert [result.tool for result in single_state.tool_results] == [
        "resolve_hero",
        "dota.hero_abilities",
    ]
    assert single_state.evidence_graph is not None
    single_evidence = single_state.evidence_graph.evidence
    assert {item.kind for item in single_evidence} == {"hero_identity", "hero_ability"}
    assert not any(item.kind == "hero_talent_tree" for item in single_evidence)
    assert any(
        item.kind == "hero_ability"
        and item.value["ability"]["internal_name"]
        == "monkey_king_boundless_strike"
        for item in single_evidence
    )


def test_complete_ability_answer_example_uses_public_language_and_talent_table() -> None:
    state, _llm = _run(
        _monkey_king_ability_plan(complete=True),
        llm=FullAbilityFormattingLLM(),
    )

    assert state.status == "ok"
    assert state.answer is not None
    rendered = state.answer.summary
    assert "等级 | 左侧天赋（中文 / English） | 右侧天赋（中文 / English）" in rendered
    for internal_name in (
        "has_shard",
        "has_scepter",
        "is_innate",
        "special_bonus_",
        "talent_internal_name",
        "internal_name",
    ):
        assert internal_name not in rendered


@pytest.mark.parametrize("query", ["ES", "definitely_missing_hero"])
def test_catalog_graph_resolver_ambiguity_and_not_found_surface_missing_evidence(
    query: str,
) -> None:
    plan = ExecutionPlan(
        intent="catalog_resolver_boundary",
        goal=f"Resolve {query}.",
        output_contract="natural_language_answer",
        tool_calls=[ToolCall(id="resolve", tool="resolve_hero", args={"query": query})],
        required_evidence=["hero_identity"],
    )

    state, _llm = _run(plan)

    assert state.status in {"error", "insufficient_evidence"}
    assert state.answer is None or state.answer.status != "ok"
    assert any(
        "hero_identity" in missing
        for attempt in state.attempts
        if attempt.evidence_summary is not None
        for missing in attempt.evidence_summary.missing_kinds
    )


def test_catalog_graph_rejects_bad_reference_before_execution() -> None:
    plan = _hero_plan("dota.hero_attributes")
    plan.tool_calls[1].args = {"hero_id": "$resolve.data.hero.missing"}

    state, llm = _run(plan)

    assert state.status == "error"
    assert state.tool_results == []
    assert state.evidence_graph is None
    assert state.answer is None
    assert any("reference path is not declared" in error for error in state.errors)
    assert isinstance(llm, CatalogAnswerLLM)
    assert llm.messages == []


def test_catalog_graph_missing_recipe_evidence_does_not_fake_recipe() -> None:
    state, _llm = _run(_item_plan("Tome of Knowledge", recipe=True))

    assert state.status in {"error", "insufficient_evidence"}
    assert any(
        "item_recipe" in missing
        for attempt in state.attempts
        if attempt.evidence_summary is not None
        for missing in attempt.evidence_summary.missing_kinds
    )


def test_catalog_graph_answer_llm_error_never_bypasses_critic_success() -> None:
    state, _llm = _run(
        _hero_plan("dota.hero_attributes"),
        llm=FailingAnswerLLM(),
    )

    assert state.status == "error"
    assert state.evidence_graph is not None
    assert state.answer is not None
    assert state.answer.status == "error"
    assert state.review is None or state.review.severity != "pass"
    assert state.response_type in {"answer_error", "replan_exhausted"}
