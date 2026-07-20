import asyncio

from app.agentic.conversation.models import ResolvedEntity, Turn
from app.agentic.graph import AgentGraphRunner
from app.agentic.planning.controller import AgentControllerResult
from app.agentic.planning.decisions import (
    ClarificationDecision,
    ContextMissingDecision,
    DirectAnswerDecision,
    normalize_controller_decision,
    validate_controller_decision,
)
from app.agentic.state import AgentRunState
from app.agentic.tools import ToolRegistry


class FakeController:
    def __init__(self, decision) -> None:
        self._result = AgentControllerResult(
            status="decided",
            reason="decision accepted",
            decision=decision,
        )

    @property
    def prompt_versions(self) -> dict[str, str]:
        return {}

    async def decide(self, query: str, game: str = "dota2", history=None):
        return self._result


def _run(decision, history: list[Turn] | None = None) -> AgentRunState:
    return asyncio.run(
        AgentGraphRunner(FakeController(decision), ToolRegistry()).run(
            AgentRunState(query="follow-up", game="dota2", history=history or [])
        )
    )


def test_quote_user_query_uses_validated_turn_and_no_tool_pipeline() -> None:
    history = [
        Turn(
            turn_index=1,
            query="选什么英雄克制 Lina？",
            status="ok",
            response_type="natural_language_answer",
            response_summary="推荐了几个对位英雄。",
        )
    ]
    decision = DirectAnswerDecision(
        kind="direct_answer",
        intent="conversation_recall",
        response_mode="quote_user_query",
        basis=[{"turn_index": 1, "field": "query"}],
    )

    state = _run(decision, history)

    assert state.status == "ok"
    assert state.response_type == "direct_answer"
    assert state.answer is not None
    assert state.answer.summary == "你上次问的是：选什么英雄克制 Lina？"
    assert state.tool_results == []
    assert state.evidence_graph is None
    assert state.review is None


def test_recall_entity_filters_entity_type_and_deduplicates_names() -> None:
    history = [
        Turn(
            turn_index=2,
            query="选什么英雄克制 Lina？",
            status="ok",
            resolved_entities=[
                ResolvedEntity(type="hero", name="Lina", id=25),
                ResolvedEntity(type="hero", name="Lina", id=25),
                ResolvedEntity(type="team", name="Liquid", id=2163),
            ],
            response_summary="推荐了几个对位英雄。",
        )
    ]
    decision = DirectAnswerDecision(
        kind="direct_answer",
        intent="conversation_recall",
        response_mode="recall_entity",
        basis=[
            {
                "turn_index": 2,
                "field": "resolved_entities",
                "entity_type": "hero",
            }
        ],
        answer="你上次提到的是影魔。",
    )

    state = _run(decision, history)

    assert state.answer is not None
    assert state.answer.summary == "你上次提到的是 Lina。"
    assert isinstance(state.decision, DirectAnswerDecision)
    assert state.decision.answer is None


def test_invalid_recall_basis_returns_redactable_validation_error() -> None:
    decision = DirectAnswerDecision(
        kind="direct_answer",
        intent="conversation_recall",
        response_mode="quote_user_query",
        basis=[{"turn_index": 99, "field": "query"}],
    )

    state = _run(decision)

    assert state.status == "error"
    assert state.response_type == "decision_validation_error"
    assert state.safe_failure_required is True
    assert state.answer is None
    assert state.evidence_graph is None


def test_failed_turn_cannot_supply_entity_or_assistant_summary_recall() -> None:
    history = [
        Turn(
            turn_index=1,
            query="bad turn",
            status="error",
            response_type="session_request_failed",
            resolved_entities=[ResolvedEntity(type="hero", name="Lina", id=25)],
            response_summary="The session request could not be completed safely.",
        )
    ]
    for mode, field in (
        ("recall_entity", "resolved_entities"),
        ("recall_assistant_summary", "response_summary"),
    ):
        decision = DirectAnswerDecision(
            kind="direct_answer",
            intent="conversation_recall",
            response_mode=mode,
            basis=[{"turn_index": 1, "field": field}],
        )
        assert _run(decision, history).response_type == "decision_validation_error"


def test_social_answer_and_non_tool_decisions_skip_evidence_and_critic() -> None:
    social = DirectAnswerDecision(
        kind="direct_answer",
        intent="social",
        response_mode="social",
        answer="你好！",
    )
    clarification = ClarificationDecision(
        kind="clarification",
        intent="position_filtered_recommendation",
        question="你说的是四号位还是五号位？",
        missing_fields=["position_ids"],
    )
    context_missing = ContextMissingDecision(
        kind="context_missing",
        intent="conversation_recall",
        reason="当前会话中没有可回忆的历史。",
    )

    social_state = _run(social)
    clarification_state = _run(clarification)
    missing_state = _run(context_missing)

    assert social_state.answer is not None
    assert social_state.answer.summary == "你好！"
    assert clarification_state.status == "clarification_required"
    assert clarification_state.response_type == "clarification"
    assert clarification_state.missing_fields == ["position_ids"]
    assert missing_state.status == "insufficient_context"
    assert missing_state.response_type == "conversation_context_missing"
    for state in (social_state, clarification_state, missing_state):
        assert state.tool_results == []
        assert state.evidence_graph is None
        assert state.review is None


def test_decision_normalization_sorts_and_deduplicates_public_lists() -> None:
    clarification = ClarificationDecision(
        kind="clarification",
        intent="clarify",
        question="请补充信息。",
        missing_fields=["role", "hero_query", "role"],
    )
    direct = DirectAnswerDecision(
        kind="direct_answer",
        intent="conversation_recall",
        response_mode="quote_user_query",
        basis=[
            {"turn_index": 2, "field": "query"},
            {"turn_index": 1, "field": "query"},
            {"turn_index": 2, "field": "query"},
        ],
        answer="模型自由复述的历史内容",
    )

    normalized_clarification = normalize_controller_decision(clarification)
    normalized_direct = normalize_controller_decision(direct)
    normalized_twice = normalize_controller_decision(normalized_direct)

    assert normalized_clarification.missing_fields == ["hero_query", "role"]
    assert [basis.turn_index for basis in normalized_direct.basis] == [1, 2]
    assert normalized_direct.answer is None
    assert normalized_twice == normalized_direct


def test_normalization_clears_all_recall_answers_and_preserves_social() -> None:
    recall_cases = (
        ("quote_user_query", "query", None),
        ("recall_entity", "resolved_entities", "hero"),
        ("recall_assistant_summary", "response_summary", None),
    )
    for mode, field, entity_type in recall_cases:
        decision = DirectAnswerDecision(
            kind="direct_answer",
            intent="conversation_recall",
            response_mode=mode,
            basis=[
                {
                    "turn_index": 1,
                    "field": field,
                    "entity_type": entity_type,
                }
            ],
            answer="不应被使用的自由回答",
        )
        assert normalize_controller_decision(decision).answer is None

    social = DirectAnswerDecision(
        kind="direct_answer",
        intent="social",
        response_mode="social",
        basis=[],
        answer="你好！",
    )
    assert normalize_controller_decision(social).answer == "你好！"


def test_unnormalized_recall_answer_validation_feedback_is_actionable() -> None:
    decision = DirectAnswerDecision(
        kind="direct_answer",
        intent="conversation_recall",
        response_mode="quote_user_query",
        basis=[{"turn_index": 1, "field": "query"}],
        answer="自由回答",
    )
    history = [
        Turn(
            turn_index=1,
            query="我上次问了什么？",
            status="ok",
            response_type="direct_answer",
        )
    ]

    errors = validate_controller_decision(decision, history, ToolRegistry())

    assert errors == [
        'For conversation recall, set "answer" to JSON null; '
        "the server renders the final answer from the validated basis"
    ]
