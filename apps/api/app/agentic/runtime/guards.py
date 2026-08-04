from typing import Literal

from app.agentic.runtime.clock import Clock
from app.agentic.runtime.models import RuntimeFailureCode
from app.agentic.state import AgentRunState
from app.observability import BUDGET

BudgetResource = Literal["controller", "tools", "answer"]


def runtime_gate_failure(
    state: AgentRunState,
    clock: Clock,
    *,
    resource: BudgetResource | None = None,
) -> RuntimeFailureCode | None:
    """Return the fixed failure code that blocks a not-yet-started operation."""

    if state.run_budget is None or state.run_started_monotonic is None:
        raise RuntimeError("runtime gate requires initialized run state")
    elapsed = max(0.0, clock.monotonic() - state.run_started_monotonic)
    if state.run_budget.deadline_exceeded(elapsed):
        return "execution_timeout"
    if resource is not None and state.run_budget.exhausted(resource):
        return "execution_budget_error"
    return None


def apply_runtime_failure(
    state: AgentRunState,
    code: RuntimeFailureCode,
    *,
    detail: str | None = None,
) -> AgentRunState:
    BUDGET.labels("deadline" if code == "execution_timeout" else "resource").inc()
    state.runtime_failure_code = code
    state.status = "error"
    state.attempt_failure_stage = "execution"
    state.reason = (
        "execution deadline exceeded"
        if code == "execution_timeout"
        else "execution budget exhausted"
    )
    message = detail or state.reason
    if message not in state.errors:
        state.errors.append(message)
    return state
