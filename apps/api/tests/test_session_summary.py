"""Tests for build_turn_summary.

Uses SimpleNamespace to construct lightweight state objects rather than
full AgentRunState instances, because summary.py accesses attributes
defensively via getattr().
"""

from types import SimpleNamespace

from app.agentic.conversation.models import Turn
from app.agentic.conversation.summary import (
    SESSION_REQUEST_FAILED_REASON,
    build_session_failure_turn,
    build_turn_summary,
    render_assistant_message,
)
from app.agentic.planning.decisions import ClarificationDecision

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _evidence_item(kind: str, subject: str, value: dict):
    return SimpleNamespace(kind=kind, subject=subject, value=value)


def _evidence_graph(items):
    return SimpleNamespace(evidence=items)


def _answer(summary: str):
    return SimpleNamespace(summary=summary)


def _plan(intent="counter_pick", context_dict=None):
    ctx = SimpleNamespace(
        model_dump=lambda mode, exclude_none: (context_dict or {})
    )
    return SimpleNamespace(intent=intent, context=ctx)


def _state(
    *,
    query="test query",
    status="ok",
    response_type="natural_language_answer",
    plan=None,
    answer=None,
    reason="",
    decision=None,
):
    return SimpleNamespace(
        query=query,
        status=status,
        response_type=response_type,
        plan=plan,
        answer=answer,
        reason=reason,
        decision=decision,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestBasicFields:
    def test_query_copied(self):
        turn = build_turn_summary(_state(query="hello dota"))
        assert turn.query == "hello dota"

    def test_status_ok(self):
        turn = build_turn_summary(_state(status="ok"))
        assert turn.status == "ok"

    def test_status_error(self):
        turn = build_turn_summary(_state(status="error"))
        assert turn.status == "error"

    def test_status_insufficient_tools(self):
        turn = build_turn_summary(_state(status="insufficient_tools"))
        assert turn.status == "insufficient_tools"

    def test_response_type_propagated(self):
        turn = build_turn_summary(_state(response_type="patch_impact_report"))
        assert turn.response_type == "patch_impact_report"

    def test_placeholder_turn_index(self):
        turn = build_turn_summary(_state())
        assert turn.turn_index == 0  # store assigns real index later

    def test_returns_turn_instance(self):
        turn = build_turn_summary(_state())
        assert isinstance(turn, Turn)


class TestIntent:
    def test_intent_from_plan(self):
        turn = build_turn_summary(_state(plan=_plan(intent="lane_outcome")))
        assert turn.intent == "lane_outcome"

    def test_intent_none_when_no_plan(self):
        turn = build_turn_summary(_state(plan=None))
        assert turn.intent is None

    def test_intent_from_non_tool_decision(self):
        decision = ClarificationDecision(
            kind="clarification",
            intent="position_filtered_recommendation",
            question="四号位还是五号位？",
            missing_fields=["position_ids"],
        )
        turn = build_turn_summary(_state(plan=None, decision=decision))
        assert turn.intent == "position_filtered_recommendation"


class TestContextScope:
    def test_scope_from_plan_context(self):
        scope = {"bracket": ["DIVINE_IMMORTAL"], "weeks_back": 2}
        turn = build_turn_summary(_state(plan=_plan(context_dict=scope)))
        assert turn.context_scope == scope

    def test_empty_scope_when_no_plan(self):
        turn = build_turn_summary(_state(plan=None))
        assert turn.context_scope == {}


class TestResponseSummary:
    def test_uses_answer_summary(self):
        turn = build_turn_summary(_state(answer=_answer("克制 Lina 的英雄…")))
        assert turn.response_summary == "克制 Lina 的英雄…"

    def test_falls_back_to_reason_on_no_answer(self):
        turn = build_turn_summary(_state(answer=None, reason="LLM disabled"))
        assert turn.response_summary == "LLM disabled"

    def test_answer_summary_truncated(self):
        long = "A" * 500
        turn = build_turn_summary(_state(answer=_answer(long)), max_summary_chars=100)
        assert len(turn.response_summary) == 100

    def test_query_truncated(self):
        long_q = "Q" * 500
        turn = build_turn_summary(_state(query=long_q), max_query_chars=50)
        assert len(turn.query) == 50

    def test_empty_summary_on_error_with_no_reason(self):
        turn = build_turn_summary(_state(status="error", answer=None, reason=""))
        assert turn.response_summary == ""

    def test_clarification_persists_question_and_missing_fields(self):
        decision = ClarificationDecision(
            kind="clarification",
            intent="position_filtered_recommendation",
            question="四号位还是五号位？",
            missing_fields=["position_ids"],
        )
        turn = build_turn_summary(
            _state(
                status="clarification_required",
                response_type="clarification",
                decision=decision,
            )
        )
        assert turn.response_summary == "四号位还是五号位？"
        assert turn.missing_fields == ["position_ids"]


def test_assistant_message_uses_the_same_visible_text_for_answer_clarification_and_boundary():
    cases = [
        (
            SimpleNamespace(
                safe_failure_required=False,
                answer=_answer("自然回答"),
                decision=None,
                reason="private answer reason",
            ),
            "自然回答",
        ),
        (
            SimpleNamespace(
                safe_failure_required=False,
                answer=None,
                decision=SimpleNamespace(question="请说明英雄名称"),
                reason="private clarification reason",
            ),
            "请说明英雄名称",
        ),
        (
            SimpleNamespace(
                safe_failure_required=False,
                answer=None,
                decision=SimpleNamespace(reason="当前没有该能力"),
                reason="private boundary reason",
            ),
            "当前没有该能力",
        ),
    ]

    for state, expected in cases:
        assert render_assistant_message(state) == expected
        assert build_turn_summary(state).response_summary == expected


def test_safe_failure_uses_public_sentinel_instead_of_private_state_reason():
    state = SimpleNamespace(
        safe_failure_required=True,
        query="query",
        status="error",
        answer=_answer("PRIVATE_ANSWER"),
        decision=SimpleNamespace(reason="PRIVATE_DECISION_REASON"),
        reason="PRIVATE_INTERNAL_REASON",
    )

    assert render_assistant_message(state) == SESSION_REQUEST_FAILED_REASON
    assert build_session_failure_turn(state).response_summary == SESSION_REQUEST_FAILED_REASON


class TestErrorState:
    def test_no_exception_when_plan_is_none(self):
        """A failed turn where plan/evidence/answer are all None must not raise."""
        state = _state(status="error", plan=None, answer=None)
        turn = build_turn_summary(state)
        assert turn.status == "error"
        assert turn.intent is None
