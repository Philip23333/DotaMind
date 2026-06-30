from app.agentic.answer import AnswerSynthesisResult
from app.agentic.critic import AgenticCritic
from app.agentic.evidence import build_evidence_graph
from app.agentic.models import ExecutionPlan, ToolResult, ToolSource
from app.agentic.stratz_tools import build_default_tool_registry
from app.core.config import Settings


def test_agentic_critic_fails_missing_evidence() -> None:
    plan = _plan()
    graph = build_evidence_graph(plan, [], _registry())
    answer = _answer(status="insufficient_evidence", confidence=0.3)

    review = AgenticCritic().review(plan, graph, answer)

    assert review.severity == "failed"
    assert any("Missing required evidence" in reason for reason in review.reasons)


def test_agentic_critic_fails_mock_when_not_allowed() -> None:
    plan = _plan()
    graph = build_evidence_graph(
        plan,
        [
            ToolResult(
                tool_call_id="resolve_target",
                tool="resolve_hero",
                status="error",
                latency_ms=1,
                source=ToolSource(name="Fixture", kind="fixture", status="mocked"),
                error="boom",
            )
        ],
        _registry(),
    )
    answer = _answer(status="insufficient_evidence", confidence=0.3)

    review = AgenticCritic().review(plan, graph, answer)

    assert review.severity == "failed"
    assert any("Mock source" in reason for reason in review.reasons)


def test_agentic_critic_fails_tool_failure() -> None:
    plan = ExecutionPlan(
        intent="counter_pick",
        goal="Fetch evidence.",
        output_contract="draft_advice",
    )
    graph = build_evidence_graph(
        plan,
        [
            ToolResult(
                tool_call_id="get_matchups",
                tool="stratz.hero_vs_hero_matchup",
                status="error",
                latency_ms=1,
                error="upstream failed",
            )
        ],
        _registry(),
    )

    review = AgenticCritic().review(plan, graph, _answer())

    assert review.severity == "failed"
    assert any("Tool failure" in reason for reason in review.reasons)


def test_agentic_critic_warns_low_answer_confidence() -> None:
    plan = ExecutionPlan(
        intent="counter_pick",
        goal="Fetch evidence.",
        output_contract="draft_advice",
    )
    graph = build_evidence_graph(plan, [], _registry())

    review = AgenticCritic().review(plan, graph, _answer(confidence=0.4))

    assert review.severity == "warning"
    assert any("below minimum" in reason for reason in review.reasons)


def test_agentic_critic_passes_valid_answer() -> None:
    plan = ExecutionPlan(
        intent="counter_pick",
        goal="Fetch evidence.",
        output_contract="draft_advice",
    )
    graph = build_evidence_graph(plan, [], _registry())

    review = AgenticCritic().review(plan, graph, _answer(confidence=0.8))

    assert review.severity == "pass"
    assert review.passed is True


def _plan() -> ExecutionPlan:
    return ExecutionPlan(
        intent="counter_pick",
        goal="Fetch evidence.",
        output_contract="draft_advice",
        required_evidence=["hero_identity"],
    )


def _answer(
    *,
    status: str = "ok",
    confidence: float = 0.8,
) -> AnswerSynthesisResult:
    return AnswerSynthesisResult(
        answer_type="draft_advice",
        status=status,
        summary="summary",
        confidence=confidence,
    )


def _registry():
    return build_default_tool_registry(
        Settings(stratz_graphql_url="https://api.stratz.test/graphql", stratz_token="token")
    )
