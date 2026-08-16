from app.agentic.conversation.summary import SESSION_REQUEST_FAILED_REASON
from app.agentic.state import AgentRunState


def _public_tool_failure_code(error_code: str | None, status: str) -> str | None:
    if status != "error":
        return None
    return {
        "reference_resolution_error": "reference_resolution_error",
        "input_validation_error": "validation_error",
        "handler_error": "handler_error",
        "tool_not_registered": "tool_error",
    }.get(error_code, "tool_error")


def response_node(state: AgentRunState) -> AgentRunState:
    if (
        state.run_context is None
        or state.run_budget is None
        or state.terminal_stage is None
        or state.run_duration_ms is None
        or len(state.attempts) not in {1, 2}
    ):
        raise RuntimeError("response_node requires one or two finalized attempts")
    expected_indexes = list(range(len(state.attempts)))
    if [attempt.attempt_index for attempt in state.attempts] != expected_indexes:
        raise RuntimeError("response_node requires contiguous attempt records")
    runtime = _public_runtime(state, safe_failure=state.safe_failure_required)
    if state.safe_failure_required:
        response_type = state.response_type or "decision_validation_error"
        state.response = {
            "query": state.query,
            "game": state.game,
            "status": "error",
            "reason": SESSION_REQUEST_FAILED_REASON,
            "response_type": response_type,
            "error_code": response_type,
            "decision_kind": None,
            "missing_fields": [],
            "planner_required_evidence": [],
            "effective_required_evidence": [],
            "required_evidence_sources": {},
            "plan": None,
            "tool_results": [],
            "evidence_graph": None,
            "answer": None,
            "review": None,
            "errors": [],
            "trace": [],
            "runtime": runtime,
        }
        return state
    state.response = state.model_dump(
        mode="json",
        include={
            "query",
            "game",
            "status",
            "reason",
            "response_type",
            "decision_kind",
            "missing_fields",
            "planner_required_evidence",
            "effective_required_evidence",
            "required_evidence_sources",
            "plan",
            "tool_results",
            "evidence_graph",
            "answer",
            "review",
            "errors",
            "trace",
        },
    )
    state.response["error_code"] = (
        state.response_type if state.status == "error" else None
    )
    state.response["errors"] = [
        "tool execution failed" if state.tool_results else "request processing failed"
        for _ in state.errors
    ]
    for item in state.response["tool_results"]:
        if item.get("status") == "error":
            item["error"] = "tool execution failed"
    state.response["runtime"] = runtime
    return state


def _public_runtime(state: AgentRunState, *, safe_failure: bool) -> dict:
    budget = state.run_budget
    context = state.run_context
    assert budget is not None and context is not None and state.terminal_stage is not None
    attempts = []
    for attempt in state.attempts:
        item = {
            "attempt_index": attempt.attempt_index,
            "decision_kind": None if safe_failure else attempt.decision_kind,
            "status": attempt.status,
            "failure_stage": attempt.failure_stage,
            "failure_code": attempt.failure_code,
            "recovery_code": attempt.recovery_code,
            "duration_ms": attempt.duration_ms,
            "tool_call_statuses": [],
            "evidence_summary": None,
            "answer_summary": None,
            "critic_summary": None,
        }
        if not safe_failure:
            item["tool_call_statuses"] = [
                {
                    "tool_call_id": call.tool_call_id,
                    "tool": call.tool,
                    "status": call.status,
                    "latency_ms": call.latency_ms,
                    "reused": call.reused,
                    "handler_entered": call.handler_entered,
                    "dispatch_stage": call.dispatch_stage,
                    "failure_code": _public_tool_failure_code(call.error_code, call.status),
                }
                for call in attempt.tool_calls
            ]
            item["evidence_summary"] = (
                attempt.evidence_summary.model_dump(mode="json")
                if attempt.evidence_summary
                else None
            )
            item["answer_summary"] = (
                attempt.answer_summary.model_dump(mode="json")
                if attempt.answer_summary
                else None
            )
            item["critic_summary"] = (
                attempt.critic_summary.model_dump(mode="json")
                if attempt.critic_summary
                else None
            )
        attempts.append(item)
    return {
        "run_id": str(context.run_id),
        "duration_ms": state.run_duration_ms,
        "terminal_stage": state.terminal_stage,
        "budget": {
            "limits": {
                "max_replans": budget.max_replans,
                "max_tool_calls_total": budget.max_tool_calls_total,
                "max_controller_calls": budget.max_controller_calls,
                "max_answer_calls": budget.max_answer_calls,
                "max_elapsed_seconds": budget.max_elapsed_seconds,
            },
            "used": {
                "replans_used": budget.replans_used,
                "tool_calls_used": budget.tool_calls_used,
                "controller_calls_used": budget.controller_calls_used,
                "answer_calls_used": budget.answer_calls_used,
            },
        },
        "attempts": attempts,
    }
