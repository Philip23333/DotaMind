"""Privacy regression tests for conversation history.

Blocking-item guard: history injected into the planner prompt must NOT leak
back to API clients via planner_prompt_messages (or anywhere in the response).
"""

import asyncio
import json
from uuid import uuid4

from app.agentic.conversation.models import Turn
from app.agentic.models import ExecutionPlan, ToolCall
from app.agentic.nodes.response import response_node
from app.agentic.planning.planner import (
    AgenticPlanner,
    AgenticPlannerResult,
    _redact_history_from_messages,
)
from app.agentic.state import AgentRunState
from app.agentic.tools.stratz_tools import build_default_tool_registry
from app.application.plan_service import PlanService
from app.application.session_store import InMemorySessionStore
from app.core.config import get_settings

SENTINEL = "SENTINEL_PRIVACY_ABC123"


async def _seed_turn(store: InMemorySessionStore, session_id: str, turn: Turn) -> None:
    async with store.transaction(session_id):
        await store.append(session_id, turn)


# ---------------------------------------------------------------------------
# Unit: redaction helper
# ---------------------------------------------------------------------------


class TestRedactHelper:
    def test_removes_history_block_from_first_user_message(self):
        history_block = f"## 对话历史\n[第1轮] 用户: 'x'\n  回答: {SENTINEL}"
        messages = [
            {"role": "system", "content": "system prompt"},
            {"role": "user", "content": f"{history_block}\n\ngame=dota2\nquery=next"},
        ]
        redacted = _redact_history_from_messages(messages, history_block)
        joined = json.dumps(redacted, ensure_ascii=False)
        assert SENTINEL not in joined
        # The actual current query must survive.
        assert "query=next" in joined
        assert "redacted" in redacted[1]["content"]

    def test_no_history_block_is_noop(self):
        messages = [
            {"role": "system", "content": "s"},
            {"role": "user", "content": "game=dota2\nquery=q"},
        ]
        redacted = _redact_history_from_messages(messages, "")
        assert redacted == messages

    def test_retry_feedback_messages_preserved(self):
        history_block = f"## 对话历史\n[第1轮] 回答: {SENTINEL}"
        messages = [
            {"role": "system", "content": "s"},
            {"role": "user", "content": f"{history_block}\n\ngame=dota2\nquery=q"},
            {"role": "assistant", "content": "prev bad json"},
            {"role": "user", "content": "retry feedback"},
        ]
        redacted = _redact_history_from_messages(messages, history_block)
        assert SENTINEL not in json.dumps(redacted, ensure_ascii=False)
        # Retry turns untouched.
        assert redacted[2]["content"] == "prev bad json"
        assert redacted[3]["content"] == "retry feedback"


# ---------------------------------------------------------------------------
# Integration: sentinel in turn 1 must not appear in turn 2 API response
# ---------------------------------------------------------------------------


class _FakeLLM:
    """Always returns insufficient_tools; enough to exercise the planner path."""

    async def complete(self, *args, **kwargs) -> str:
        return ""

    async def complete_json(self, messages, **kwargs) -> dict:
        return {"status": "insufficient_tools", "reason": "no tool", "plan": None}

    async def complete_with_tools(self, *args, **kwargs):
        return None


def test_prior_turn_sentinel_absent_from_next_turn_response():
    registry = build_default_tool_registry(get_settings())
    planner = AgenticPlanner(registry, llm=_FakeLLM(), llm_enabled=True)
    store = InMemorySessionStore()
    service = PlanService(planner=planner, session_store=store)
    sid = uuid4()

    async def _scenario():
        # Seed turn 1 with a sentinel in its answer summary.
        await _seed_turn(
            store,
            str(sid),
            Turn(
                query="turn one",
                status="ok",
                intent="counter_pick",
                response_summary=SENTINEL,
            ),
        )
        # Turn 2: planner injects turn-1 history (with sentinel) then redacts it.
        return await service.run("turn two", session_id=sid)

    result = asyncio.run(_scenario())

    # The full API-facing response must not contain the sentinel anywhere,
    # including planner_prompt_messages.
    response_json = json.dumps(result.response, ensure_ascii=False)
    assert SENTINEL not in response_json, "history leaked into API response"


def test_history_field_excluded_from_response():
    """AgentRunState.history must not be serialised into the response dict."""
    registry = build_default_tool_registry(get_settings())
    planner = AgenticPlanner(registry, llm=_FakeLLM(), llm_enabled=True)
    store = InMemorySessionStore()
    service = PlanService(planner=planner, session_store=store)
    sid = uuid4()

    async def _scenario():
        await _seed_turn(
            store, str(sid), Turn(query="one", response_summary=SENTINEL)
        )
        return await service.run("two", session_id=sid)

    result = asyncio.run(_scenario())
    assert "history" not in (result.response or {})


def test_stateful_validator_failure_uses_sentinel_free_public_envelope():
    rejected_plan = ExecutionPlan(
        intent="bad",
        goal=SENTINEL,
        output_contract="natural_language_answer",
        tool_calls=[ToolCall(id="bad", tool="resolve_hero", args={"query": SENTINEL})],
    )
    state = AgentRunState(
        query="current query",
        game="dota2",
        session_memory_enabled=True,
        validation_failed=True,
        status="error",
        reason=SENTINEL,
        errors=[SENTINEL],
        plan=rejected_plan,
        planning=AgenticPlannerResult(
            status="planned",
            reason=SENTINEL,
            plan=rejected_plan,
            errors=[SENTINEL],
            raw_output={"echo": SENTINEL},
            raw_content=SENTINEL,
            prompt_messages=[{"role": "user", "content": SENTINEL}],
        ),
    )

    response = response_node(state).response

    assert response is not None
    assert SENTINEL not in json.dumps(response, ensure_ascii=False)
    assert response["error_code"] == "session_request_failed"
    assert response["plan"] is None


def test_stateful_safe_failure_persists_only_stable_redacted_turn():
    rejected_plan = ExecutionPlan(
        intent="bad",
        goal=SENTINEL,
        output_contract="natural_language_answer",
        tool_calls=[ToolCall(id="bad", tool="resolve_hero", args={"query": SENTINEL})],
    )

    class UnsafeRunner:
        async def run(self, _input_state: AgentRunState) -> AgentRunState:
            unsafe_state = AgentRunState(
                query="current query",
                game="dota2",
                session_memory_enabled=True,
                validation_failed=True,
                status="error",
                reason=SENTINEL,
                errors=[SENTINEL],
                plan=rejected_plan,
                planning=AgenticPlannerResult(
                    status="planned",
                    reason=SENTINEL,
                    plan=rejected_plan,
                    raw_content=SENTINEL,
                    prompt_messages=[{"role": "user", "content": SENTINEL}],
                ),
            )
            return response_node(unsafe_state)

    store = InMemorySessionStore()
    service = PlanService(session_store=store)
    service.runner = UnsafeRunner()  # type: ignore[assignment]
    sid = uuid4()

    async def _scenario():
        result = await service.run("current query", session_id=sid)
        turns = await store.get(str(sid), limit=5)
        return result, turns

    result, turns = asyncio.run(_scenario())

    assert result.response_type == "session_request_failed"
    assert len(turns) == 1
    turn = turns[0]
    assert turn.response_type == "session_request_failed"
    assert turn.response_summary == "The session request could not be completed safely."
    assert turn.intent is None
    assert turn.context_scope == {}
    assert turn.resolved_entities == []
    assert SENTINEL not in turn.model_dump_json()
