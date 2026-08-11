import asyncio

from app.agentic.conversation.models import ConversationMessage
from app.agentic.graph import AgentGraphRunner
from app.agentic.models import ExecutionPlan, ToolCall
from app.agentic.planning.controller import AgentControllerResult
from app.agentic.planning.decisions import (
    ClarificationDecision,
    ContextMissingDecision,
    DirectAnswerDecision,
    ToolPlanDecision,
    normalize_controller_decision,
    validate_controller_decision,
)
from app.agentic.state import AgentRunState
from app.agentic.tools import ToolRegistry
from app.agentic.tools.conversation_tools import register_conversation_tools


class FakeController:
    def __init__(self, decision) -> None:
        self._result = AgentControllerResult(
            status="decided", reason="decision accepted", decision=decision
        )

    @property
    def prompt_versions(self) -> dict[str, str]:
        return {}

    async def decide(self, *args, **kwargs):
        return self._result


def _run(decision, messages=None, query="follow-up") -> AgentRunState:
    return asyncio.run(
        AgentGraphRunner(FakeController(decision), ToolRegistry()).run(
            AgentRunState(
                query=query,
                game="dota2",
                recent_messages=messages or [],
            )
        )
    )


def test_quote_user_query_uses_validated_message_and_no_tool_pipeline() -> None:
    messages = [ConversationMessage(turn_index=1, role="user", content="选什么英雄克制 Lina？")]
    decision = DirectAnswerDecision(
        kind="direct_answer",
        intent="conversation_recall",
        response_mode="quote_user_query",
        basis=[{"turn_index": 1, "role": "user"}],
    )
    state = _run(decision, messages)
    assert state.answer is not None
    assert state.answer.summary == "你上次问的是：选什么英雄克制 Lina？"
    assert state.tool_results == []


def test_recall_assistant_summary_uses_validated_assistant_message() -> None:
    messages = [ConversationMessage(turn_index=1, role="assistant", content="Lina 有四个技能。")]
    decision = DirectAnswerDecision(
        kind="direct_answer",
        intent="conversation_recall",
        response_mode="recall_assistant_summary",
        basis=[{"turn_index": 1, "role": "assistant"}],
    )
    state = _run(decision, messages, query="刚才怎么说的？")
    assert state.answer is not None
    assert state.answer.summary == "我当时的回答摘要是：Lina 有四个技能。"


def test_clarification_and_context_missing_skip_tools() -> None:
    clarification = ClarificationDecision(
        kind="clarification",
        intent="clarify",
        question="你说的是四号位还是五号位？",
        missing_fields=["position_ids"],
    )
    missing = ContextMissingDecision(
        kind="context_missing",
        intent="conversation_recall",
        reason="当前会话中没有可回忆的历史。",
    )
    assert _run(clarification).status == "clarification_required"
    assert _run(missing).status == "insufficient_context"


def test_normalization_is_deterministic_and_clears_free_recall_text() -> None:
    decision = DirectAnswerDecision(
        kind="direct_answer",
        intent="conversation_recall",
        response_mode="quote_user_query",
        basis=[
            {"turn_index": 2, "role": "user"},
            {"turn_index": 1, "role": "user"},
            {"turn_index": 2, "role": "user"},
        ],
        answer="do not use",
    )
    normalized = normalize_controller_decision(decision)
    assert [item.turn_index for item in normalized.basis] == [1, 2]
    assert normalized.answer is None


def test_recall_basis_requires_existing_message_and_role() -> None:
    decision = DirectAnswerDecision(
        kind="direct_answer",
        intent="conversation_recall",
        response_mode="recall_assistant_summary",
        basis=[{"turn_index": 1, "role": "assistant"}],
    )
    errors = validate_controller_decision(
        decision,
        [ConversationMessage(turn_index=1, role="user", content="上次")],
        ToolRegistry(),
    )
    assert any("message is unavailable" in error for error in errors)


def test_clarification_accepts_open_snake_case_missing_field_names() -> None:
    decision = ClarificationDecision(
        kind="clarification",
        intent="hero_ability",
        question="请说明英雄名称。",
        missing_fields=["hero_name", "ability_name"],
    )

    assert decision.missing_fields == ["hero_name", "ability_name"]


def test_history_lookup_plan_must_be_single_tool_without_evidence() -> None:
    registry = ToolRegistry()
    register_conversation_tools(registry)
    valid_plan = ExecutionPlan(
        intent="conversation_recall",
        goal="Find the earlier clarification.",
        output_contract="natural_language_answer",
        tool_calls=[
            ToolCall(
                id="history",
                tool="conversation.history_lookup",
                args={"query_text": "技能冷却"},
            )
        ],
        required_evidence=[],
    )
    mixed_plan = valid_plan.model_copy(
        update={
            "tool_calls": [
                *valid_plan.tool_calls,
                ToolCall(id="hero", tool="resolve_hero", args={"query": "狼人"}),
            ]
        }
    )
    evidence_plan = valid_plan.model_copy(update={"required_evidence": ["history"]})

    assert validate_controller_decision(
        ToolPlanDecision(kind="tool_plan", plan=valid_plan),
        [],
        registry,
    ) == []
    assert any(
        "only tool call" in error
        for error in validate_controller_decision(
            ToolPlanDecision(kind="tool_plan", plan=mixed_plan),
            [],
            registry,
        )
    )
    assert any(
        "required_evidence" in error
        for error in validate_controller_decision(
            ToolPlanDecision(kind="tool_plan", plan=evidence_plan),
            [],
            registry,
        )
    )
