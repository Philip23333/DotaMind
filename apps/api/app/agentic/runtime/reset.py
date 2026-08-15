from copy import deepcopy
from datetime import datetime

from app.agentic.state import AgentRunState


def reset_attempt_working_state(
    state: AgentRunState,
    *,
    next_attempt_index: int,
    started_at: datetime,
    started_monotonic: float,
) -> AgentRunState:
    """Return a new state with only attempt-local working data reset."""
    updates = {
        "recent_messages": deepcopy(state.recent_messages),
        "retrieved_messages": deepcopy(state.retrieved_messages),
        "controller_context_summaries": deepcopy(
            state.controller_context_summaries
        ),
        "next_turn_index": state.next_turn_index,
        "run_context": state.run_context.model_copy(deep=True) if state.run_context else None,
        "run_budget": state.run_budget.model_copy(deep=True) if state.run_budget else None,
        "attempts": deepcopy(state.attempts),
        "trace": deepcopy(state.trace),
        "recovery_action": None,
        "recovery_feedback": (
            state.recovery_feedback.model_copy(deep=True)
            if state.recovery_feedback
            else None
        ),
        "recovery_baseline_decision": (
            state.recovery_baseline_decision.model_copy(deep=True)
            if state.recovery_baseline_decision
            else None
        ),
        "executed_call_fingerprints": {
            fingerprint: cached.model_copy(deep=True)
            for fingerprint, cached in state.executed_call_fingerprints.items()
        },
        "runtime_failure_code": None,
        "attempt_index": next_attempt_index,
        "attempt_started_at": started_at,
        "attempt_started_monotonic": started_monotonic,
        "attempt_failure_stage": None,
        "terminal_stage": None,
        "run_duration_ms": None,
        "validation_failed": False,
        "safe_failure_required": False,
        "controller_result": None,
        "decision": None,
        "decision_kind": None,
        "missing_fields": [],
        "plan": None,
        "planner_required_evidence": [],
        "global_required_evidence": [],
        "effective_required_evidence": [],
        "required_evidence_sources": {},
        "mandatory_evidence_by_call": {},
        "tool_results": [],
        "tool_dispatch_records": [],
        "evidence_graph": None,
        "answer": None,
        "review": None,
        "status": "error",
        "reason": "",
        "errors": [],
        "response_type": None,
        "response": None,
    }
    return state.model_copy(update=updates, deep=False)
