from app.agentic.planning.contracts import get_contract
from app.agentic.planning.decisions import ConversationAnswerResult
from app.agentic.runtime.models import (
    AttemptAnswerSummary,
    AttemptCriticSummary,
    AttemptEvidenceSummary,
    AttemptPlanSummary,
    AttemptRecord,
    AttemptToolCallSummary,
    TerminalOutcome,
)
from app.agentic.state import AgentRunState


def resolve_terminal_outcome(state: AgentRunState) -> TerminalOutcome:
    result = state.controller_result
    if result is not None and result.status == "error":
        response_type = result.failure_type or "planning_error"
        failure_stage = (
            "decision_validation"
            if response_type == "decision_validation_error"
            else "controller"
        )
        return _outcome("error", response_type, "controller", failure_stage)
    if state.validation_failed:
        stage = state.attempt_failure_stage or "decision_validation"
        return _outcome("error", "decision_validation_error", stage, stage)
    if any(item.status == "error" for item in state.tool_results):
        return _outcome("error", "tool_error", "tool_execution", "tool_execution")
    if state.answer is not None and state.answer.status == "error":
        return _outcome("error", "answer_error", "answer", "answer")
    if state.runtime_failure_code is not None:
        return _outcome(
            "error",
            state.runtime_failure_code,
            "execution",
            "execution",
        )
    if (
        state.response_type == "replan_exhausted"
        and state.evidence_graph is not None
        and state.evidence_graph.missing
    ):
        return _outcome(
            "insufficient_evidence",
            "replan_exhausted",
            "evidence",
            "evidence",
        )
    if state.evidence_graph is not None and state.evidence_graph.missing:
        return _outcome(
            "insufficient_evidence",
            "insufficient_evidence",
            "evidence",
            "evidence",
        )
    if state.answer is not None and state.answer.status == "insufficient_evidence":
        return _outcome(
            "insufficient_evidence",
            "insufficient_evidence",
            "evidence",
            "evidence",
        )
    if state.review is not None and not state.review.passed:
        return _outcome(
            "insufficient_evidence",
            "insufficient_evidence",
            "critic",
            "critic",
        )
    if state.status == "clarification_required":
        return _outcome(state.status, "clarification", "decision_validation", None, state.reason)
    if state.status == "insufficient_context":
        return _outcome(
            state.status,
            "conversation_context_missing",
            "decision_validation",
            None,
            state.reason,
        )
    if state.status == "insufficient_tools":
        return _outcome(
            state.status,
            "capability_boundary",
            "decision_validation",
            None,
            state.reason,
        )
    if isinstance(state.answer, ConversationAnswerResult):
        return _outcome("ok", "direct_answer", "conversation_answer", None, state.reason)
    if state.status == "error":
        return _outcome("error", "execution_error", "execution", "execution")
    response_type = _successful_response_type(state)
    terminal_stage = "critic" if state.review is not None else "answer"
    return _outcome("ok", response_type, terminal_stage, None, state.reason)


def build_attempt_record(
    state: AgentRunState,
    outcome: TerminalOutcome,
    *,
    duration_ms: int,
) -> AttemptRecord:
    if state.attempt_started_at is None:
        raise RuntimeError("attempt start time is missing")
    dispatch_by_id = {item.tool_call_id: item for item in state.tool_dispatch_records}
    if len(dispatch_by_id) != len(state.tool_dispatch_records):
        raise RuntimeError("duplicate tool dispatch record")
    tool_calls: list[AttemptToolCallSummary] = []
    for result in state.tool_results:
        dispatch = dispatch_by_id.get(result.tool_call_id)
        if dispatch is None:
            raise RuntimeError(f"missing tool dispatch record: {result.tool_call_id}")
        tool_calls.append(
            AttemptToolCallSummary(
                tool_call_id=result.tool_call_id,
                tool=result.tool,
                status=result.status,
                latency_ms=result.latency_ms,
                handler_entered=dispatch.handler_entered,
                dispatch_stage=dispatch.stage,
                error_code=dispatch.error_code,
                reused=dispatch.stage == "cache_reuse",
            )
        )
    return AttemptRecord(
        attempt_index=state.attempt_index,
        decision_kind=state.decision_kind,
        plan_summary=_plan_summary(state),
        tool_calls=tool_calls,
        evidence_summary=_evidence_summary(state),
        answer_summary=_answer_summary(state),
        critic_summary=_critic_summary(state),
        status=outcome.attempt_status,
        failure_stage=outcome.failure_stage,
        recovery_code=(
            state.recovery_feedback.code
            if state.attempt_index == 1 and state.recovery_feedback is not None
            else None
        ),
        started_at=state.attempt_started_at,
        duration_ms=duration_ms,
    )


def _outcome(status, response_type, terminal_stage, failure_stage, reason=""):
    stable = {
        "planning_error": "planning failed",
        "decision_validation_error": "decision validation failed",
        "tool_error": "tool execution failed",
        "answer_error": "answer generation failed",
        "execution_error": "execution failed",
        "execution_budget_error": "execution budget exhausted",
        "execution_timeout": "execution deadline exceeded",
        "insufficient_evidence": "insufficient evidence",
        "replan_exhausted": "replan exhausted",
    }.get(response_type, reason)
    return TerminalOutcome(
        public_status=status,
        response_type=response_type,
        stable_reason=stable,
        attempt_status=status,
        terminal_stage=terminal_stage,
        failure_stage=failure_stage,
    )


def _successful_response_type(state: AgentRunState) -> str:
    if state.answer is None:
        return "raw_tool_results"
    contract = get_contract(state.answer.answer_type)
    if state.answer.status == "ok" and contract is not None:
        return state.answer.answer_type
    if state.answer.status == "unsupported_output_contract":
        return "unsupported_answer"
    return "raw_tool_results"


def _plan_summary(state: AgentRunState) -> AttemptPlanSummary | None:
    if state.plan is None:
        return None
    return AttemptPlanSummary(
        output_contract=state.plan.output_contract,
        tool_call_count=len(state.plan.tool_calls),
        effective_required_evidence=list(state.effective_required_evidence),
    )


def _evidence_summary(state: AgentRunState) -> AttemptEvidenceSummary | None:
    graph = state.evidence_graph
    if graph is None:
        return None
    present = sorted({item.kind for item in graph.evidence})
    return AttemptEvidenceSummary(
        required_kinds=list(graph.required_evidence),
        present_kinds=present,
        missing_kinds=list(graph.missing),
        completeness=graph.data_quality.completeness,
        mock_used=graph.data_quality.mock_used,
        evidence_count=len(graph.evidence),
    )


def _answer_summary(state: AgentRunState) -> AttemptAnswerSummary | None:
    if state.answer is None:
        return None
    confidence = getattr(state.answer, "confidence", None)
    return AttemptAnswerSummary(
        answer_type=state.answer.answer_type,
        status=state.answer.status,
        confidence=confidence,
    )


def _critic_summary(state: AgentRunState) -> AttemptCriticSummary | None:
    if state.review is None:
        return None
    return AttemptCriticSummary(
        passed=state.review.passed,
        severity=state.review.severity,
        issue_count=len(state.review.reasons),
    )
