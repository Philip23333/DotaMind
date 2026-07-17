"""Tests for build_turn_summary.

Uses SimpleNamespace to construct lightweight state objects rather than
full AgentRunState instances, because summary.py accesses attributes
defensively via getattr().
"""

from types import SimpleNamespace

import pytest

from app.agentic.conversation.models import Turn
from app.agentic.conversation.summary import build_turn_summary


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
    evidence_graph=None,
    reason="",
):
    return SimpleNamespace(
        query=query,
        status=status,
        response_type=response_type,
        plan=plan,
        answer=answer,
        evidence_graph=evidence_graph,
        reason=reason,
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


class TestResolvedEntities:
    def test_hero_identity_extracted(self):
        items = [_evidence_item("hero_identity", "Lina", {"localized_name": "Lina", "hero_id": 25})]
        turn = build_turn_summary(_state(evidence_graph=_evidence_graph(items)))
        assert len(turn.resolved_entities) == 1
        e = turn.resolved_entities[0]
        assert e.type == "hero"
        assert e.name == "Lina"
        assert e.id == 25

    def test_hero_uses_subject_when_no_localized_name(self):
        items = [_evidence_item("hero_identity", "Subject Hero", {"hero_id": 10})]
        turn = build_turn_summary(_state(evidence_graph=_evidence_graph(items)))
        assert turn.resolved_entities[0].name == "Subject Hero"

    def test_team_identity_extracted(self):
        items = [_evidence_item("team_identity", "XG", {"team_id": 999})]
        turn = build_turn_summary(_state(evidence_graph=_evidence_graph(items)))
        e = turn.resolved_entities[0]
        assert e.type == "team"
        assert e.name == "XG"
        assert e.id == 999

    def test_player_identity_extracted(self):
        items = [_evidence_item("player_identity", "SomePlayer", {"steam_account_id": 853634884})]
        turn = build_turn_summary(_state(evidence_graph=_evidence_graph(items)))
        e = turn.resolved_entities[0]
        assert e.type == "player"
        assert e.id == 853634884

    def test_unknown_evidence_kind_ignored(self):
        items = [_evidence_item("matchup_ranking_row", "x", {})]
        turn = build_turn_summary(_state(evidence_graph=_evidence_graph(items)))
        assert turn.resolved_entities == []

    def test_multiple_entity_kinds(self):
        items = [
            _evidence_item("hero_identity", "Lina", {"hero_id": 25}),
            _evidence_item("team_identity", "XG", {"team_id": 1}),
        ]
        turn = build_turn_summary(_state(evidence_graph=_evidence_graph(items)))
        types = {e.type for e in turn.resolved_entities}
        assert types == {"hero", "team"}


class TestErrorState:
    def test_no_exception_when_plan_is_none(self):
        """A failed turn where plan/evidence/answer are all None must not raise."""
        state = _state(status="error", plan=None, evidence_graph=None, answer=None)
        turn = build_turn_summary(state)
        assert turn.status == "error"
        assert turn.intent is None
        assert turn.resolved_entities == []

    def test_no_exception_when_evidence_graph_is_none(self):
        turn = build_turn_summary(_state(evidence_graph=None))
        assert turn.resolved_entities == []
