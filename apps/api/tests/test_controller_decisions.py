import asyncio

import pytest
from pydantic import BaseModel, ValidationError

from app.agentic.conversation.models import ConversationMessage
from app.agentic.graph import AgentGraphRunner
from app.agentic.models import ExecutionPlan, ToolCall
from app.agentic.planning.controller import AgentControllerResult
from app.agentic.planning.decisions import (
    ClarificationDecision,
    ContextMissingDecision,
    DirectAnswerDecision,
    ToolPlanDecision,
    validate_controller_decision,
)
from app.agentic.state import AgentRunState
from app.agentic.tools import ToolDefinition, ToolRegistry
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


def test_direct_answer_uses_controller_text_and_no_tool_pipeline() -> None:
    decision = DirectAnswerDecision(
        kind="direct_answer",
        intent="conversation_recall",
        answer="你上一轮是在问选什么英雄克制 Lina。",
    )
    state = _run(decision)
    assert state.answer is not None
    assert state.answer.summary == "你上一轮是在问选什么英雄克制 Lina。"
    assert state.tool_results == []
    assert state.response_type == "direct_answer"


def test_direct_answer_can_reuse_conversation_without_basis_or_tools() -> None:
    messages = [
        ConversationMessage(turn_index=1, role="user", content="狼人有什么技能？"),
        ConversationMessage(
            turn_index=1,
            role="assistant",
            content="召狼的冷却时间是30秒（7.41e）。",
        ),
    ]
    decision = DirectAnswerDecision(
        kind="direct_answer",
        intent="hero_ability",
        answer="沿用上一轮 7.41e 数据，召狼的冷却时间是30秒。",
    )

    state = _run(decision, messages, query="它还是30秒吗？")

    assert state.answer is not None
    assert state.answer.summary == "沿用上一轮 7.41e 数据，召狼的冷却时间是30秒。"
    assert state.tool_results == []
    assert state.response_type == "direct_answer"
    assert any("direct answer completed" in event.action for event in state.trace)


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


def test_direct_answer_has_no_legacy_mode_or_basis_fields() -> None:
    with pytest.raises(ValidationError):
        DirectAnswerDecision(
            kind="direct_answer",
            intent="conversation_recall",
            answer="回答",
            response_mode="history_grounded_answer",
        )


def test_direct_answer_validation_does_not_route_on_history() -> None:
    decision = DirectAnswerDecision(
        kind="direct_answer",
        intent="conversation_recall",
        answer="回答",
    )
    assert validate_controller_decision(decision, [], ToolRegistry()) == []


def test_clarification_accepts_open_snake_case_missing_field_names() -> None:
    decision = ClarificationDecision(
        kind="clarification",
        intent="hero_ability",
        question="请说明英雄名称。",
        missing_fields=["hero_name", "ability_name"],
    )

    assert decision.missing_fields == ["hero_name", "ability_name"]


class _NoArgs(BaseModel):
    pass


def test_controller_context_plan_cannot_mix_destinations_or_request_evidence() -> None:
    registry = ToolRegistry()
    register_conversation_tools(registry)
    registry.register(
        ToolDefinition(
            name="debug.evidence",
            description="Return evidence-routed debug data.",
            input_model=_NoArgs,
            handler=lambda args, context: {},
        )
    )
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
                ToolCall(id="debug", tool="debug.evidence", args={}),
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
        "must not be mixed with evidence tools" in error
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
