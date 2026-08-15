import asyncio
from uuid import uuid4

import pytest

from app.agentic.conversation.models import DialogueTurn
from app.agentic.graph import AgentGraphRunner
from app.agentic.models import ExecutionPlan, QueryContext, ToolCall
from app.agentic.planning.controller import AgentControllerResult
from app.agentic.planning.decisions import ContextMissingDecision, ToolPlanDecision
from app.agentic.state import AgentRunState
from app.agentic.tools import ToolRegistry
from app.agentic.tools.conversation_tools import (
    ConversationHistoryLookupInput,
    _history_lookup_handler,
    register_conversation_tools,
)
from app.application.history_lookup import HistoryLookupContext, bind_history_lookup_context
from app.core.config import RuntimePolicy


class _Repository:
    def __init__(self) -> None:
        self.calls = 0

    async def lookup_dialogue(self, *args, **kwargs):
        self.calls += 1
        return [
            DialogueTurn(
                turn_index=2,
                user_message="狼人有什么技能",
                assistant_message="召狼、嗥叫、变身。",
            )
        ]


def test_history_lookup_returns_messages_without_exposing_session_ids() -> None:
    async def scenario() -> None:
        context = HistoryLookupContext(
            chat_repository=_Repository(),  # type: ignore[arg-type]
            browser_id="browser",
            session_id=uuid4(),
        )
        with bind_history_lookup_context(context):
            result = await _history_lookup_handler(
                ConversationHistoryLookupInput(query_text="狼人"), QueryContext()
            )

        assert result["turn_indexes"] == [2]
        assert result["messages"] == [
            {
                "turn_index": 2,
                "role": "user",
                "content": "狼人有什么技能",
            },
            {
                "turn_index": 2,
                "role": "assistant",
                "content": "召狼、嗥叫、变身。",
            },
        ]
        assert "browser" not in str(result)

    asyncio.run(scenario())


def test_history_lookup_requires_request_context() -> None:
    async def scenario() -> None:
        with pytest.raises(RuntimeError, match="only available during a chat run"):
            await _history_lookup_handler(
                ConversationHistoryLookupInput(query_text="狼人"), QueryContext()
            )

    asyncio.run(scenario())


def test_history_lookup_requires_selector_and_normalizes_turn_indexes() -> None:
    with pytest.raises(ValueError, match="requires query_text"):
        ConversationHistoryLookupInput()

    with pytest.raises(ValueError, match="positive turn indexes"):
        ConversationHistoryLookupInput(turn_indexes=[0])

    args = ConversationHistoryLookupInput(turn_indexes=[3, 3, 1])
    assert args.turn_indexes == [3, 1]


def test_history_lookup_accepts_any_single_selector() -> None:
    assert ConversationHistoryLookupInput(before_turn_index=4).before_turn_index == 4


class _SequenceController:
    prompt_versions: dict[str, str] = {}

    def __init__(self, decisions) -> None:
        self.decisions = list(decisions)
        self.seen_retrieved: list[list] = []

    async def decide(self, *args, retrieved_messages=None, **kwargs):
        self.seen_retrieved.append(list(retrieved_messages or []))
        return AgentControllerResult(
            status="decided",
            reason="decision accepted",
            decision=self.decisions.pop(0),
        )


def _history_plan() -> ToolPlanDecision:
    return ToolPlanDecision(
        kind="tool_plan",
        plan=ExecutionPlan(
            intent="conversation_recall",
            goal="Find older dialogue.",
            output_contract="natural_language_answer",
            tool_calls=[
                ToolCall(
                    id="history",
                    tool="conversation.history_lookup",
                    args={"query_text": "狼人"},
                )
            ],
            required_evidence=[],
        ),
    )


def test_history_lookup_messages_reach_the_next_controller_call() -> None:
    async def scenario() -> None:
        repository = _Repository()
        controller = _SequenceController(
            [
                _history_plan(),
                ContextMissingDecision(
                    kind="context_missing",
                    intent="conversation_recall",
                    reason="未找到更早对话。",
                ),
            ]
        )
        registry = ToolRegistry()
        register_conversation_tools(registry)
        runner = AgentGraphRunner(controller, registry)
        context = HistoryLookupContext(
            chat_repository=repository,  # type: ignore[arg-type]
            browser_id="browser",
            session_id=uuid4(),
        )
        with bind_history_lookup_context(context):
            state = await runner.run(AgentRunState(query="刚才提到什么？", game="dota2"))

        assert repository.calls == 1
        assert len(controller.seen_retrieved) == 2
        assert [message.content for message in controller.seen_retrieved[1]] == [
            "狼人有什么技能",
            "召狼、嗥叫、变身。",
        ]
        assert state.history_lookup_count == 1

    asyncio.run(scenario())


def test_history_lookup_limit_blocks_second_execution_before_tool_handler() -> None:
    async def scenario() -> None:
        repository = _Repository()
        controller = _SequenceController([_history_plan(), _history_plan()])
        registry = ToolRegistry()
        register_conversation_tools(registry)
        runner = AgentGraphRunner(controller, registry, history_lookup_max_per_run=1)
        context = HistoryLookupContext(
            chat_repository=repository,  # type: ignore[arg-type]
            browser_id="browser",
            session_id=uuid4(),
        )
        with bind_history_lookup_context(context):
            state = await runner.run(AgentRunState(query="再查一次", game="dota2"))

        assert state.history_lookup_count == 1
        assert repository.calls == 1
        assert state.status == "error"
        assert len(controller.seen_retrieved) == 2

    asyncio.run(scenario())


def test_history_lookup_budget_allows_final_controller_after_two_lookups() -> None:
    async def scenario() -> None:
        repository = _Repository()
        controller = _SequenceController(
            [
                _history_plan(),
                _history_plan(),
                ContextMissingDecision(
                    kind="context_missing",
                    intent="conversation_recall",
                    reason="未找到更早对话。",
                ),
            ]
        )
        registry = ToolRegistry()
        register_conversation_tools(registry)
        runner = AgentGraphRunner(
            controller,
            registry,
            runtime_policy=RuntimePolicy(max_controller_calls=3),
            history_lookup_max_per_run=2,
        )
        context = HistoryLookupContext(
            chat_repository=repository,  # type: ignore[arg-type]
            browser_id="browser",
            session_id=uuid4(),
        )
        with bind_history_lookup_context(context):
            state = await runner.run(AgentRunState(query="查两次", game="dota2"))

        assert state.history_lookup_count == 2
        assert len(controller.seen_retrieved) == 3
        assert state.status == "insufficient_context"

    asyncio.run(scenario())
