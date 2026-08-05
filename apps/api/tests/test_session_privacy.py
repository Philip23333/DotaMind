"""Privacy regression tests for conversation history.

Blocking-item guard: history injected into the planner prompt must NOT leak
back to API clients through any public response field.
"""

import json

from app.agentic.models import ExecutionPlan, ToolCall
from app.agentic.nodes.attempt_finalize import attempt_finalize_node
from app.agentic.nodes.response import response_node
from app.agentic.nodes.run_finalize import run_finalize_node
from app.agentic.nodes.run_init import run_init_node
from app.agentic.planning.controller import AgentControllerResult, _redact_history_from_messages
from app.agentic.planning.decisions import (
    CapabilityBoundaryDecision,
    ToolPlanDecision,
)
from app.agentic.runtime.clock import SystemClock
from app.agentic.state import AgentRunState
from app.core.config import RuntimePolicy

SENTINEL = "SENTINEL_PRIVACY_ABC123"


def _finalize_response(state: AgentRunState) -> AgentRunState:
    clock = SystemClock()
    run_init_node(state, RuntimePolicy(), clock)
    attempt_finalize_node(state, clock)
    run_finalize_node(state, clock)
    return response_node(state)


def test_stateless_response_excludes_raw_controller_debug_data() -> None:
    decision = CapabilityBoundaryDecision(
        kind="capability_boundary",
        intent="unsupported",
        reason="No registered capability.",
    )
    state = AgentRunState(
        query="debug",
        game="dota2",
        status="insufficient_tools",
        decision=decision,
        decision_kind=decision.kind,
        controller_result=AgentControllerResult(
            status="decided",
            reason="decision accepted",
            decision=decision,
            raw_output={"sentinel": SENTINEL},
            raw_content=SENTINEL,
            prompt_messages=[{"role": "user", "content": SENTINEL}],
        ),
    )

    response = _finalize_response(state).response

    assert response is not None
    assert SENTINEL not in json.dumps(response, ensure_ascii=False)
    assert not any(key.startswith("controller_") for key in response)


def test_stateless_validation_failure_uses_redacted_public_envelope() -> None:
    state = AgentRunState(
        query="current query",
        game="dota2",
        status="error",
        validation_failed=True,
        safe_failure_required=True,
        reason=SENTINEL,
        errors=[SENTINEL],
    )

    response = _finalize_response(state).response

    assert response is not None
    assert response["response_type"] == "decision_validation_error"
    assert response["errors"] == []
    assert SENTINEL not in json.dumps(response, ensure_ascii=False)


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


def test_validator_failure_uses_sentinel_free_public_envelope():
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
        safe_failure_required=True,
        controller_result=AgentControllerResult(
            status="decided",
            reason=SENTINEL,
            decision=ToolPlanDecision(kind="tool_plan", plan=rejected_plan),
            errors=[SENTINEL],
            raw_output={"echo": SENTINEL},
            raw_content=SENTINEL,
            prompt_messages=[{"role": "user", "content": SENTINEL}],
        ),
    )

    response = _finalize_response(state).response

    assert response is not None
    assert SENTINEL not in json.dumps(response, ensure_ascii=False)
    assert response["error_code"] == "decision_validation_error"
    assert response["plan"] is None
