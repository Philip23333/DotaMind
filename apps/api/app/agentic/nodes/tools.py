import logging
from typing import Any

from app.agentic.models import ToolCall, ToolResult
from app.agentic.references import lookup_path, parse_reference
from app.agentic.runtime.clock import Clock
from app.agentic.runtime.guards import apply_runtime_failure, runtime_gate_failure
from app.agentic.runtime.models import (
    CachedToolCall,
    RuntimeFailureCode,
    ToolDispatchRecord,
)
from app.agentic.runtime.recovery import tool_call_fingerprint
from app.agentic.state import AgentRunState
from app.agentic.tools.executor import ToolExecutor

logger = logging.getLogger(__name__)


class _RuntimeGateBlocked(RuntimeError):
    def __init__(self, code: RuntimeFailureCode) -> None:
        self.code = code
        super().__init__(code)


async def tool_executor_node(
    state: AgentRunState,
    executor: ToolExecutor,
    clock: Clock,
) -> AgentRunState:
    state.add_trace("tools", "execute planned tool calls", "planned")
    logger.info(
        "node=tools start tool_calls=%s",
        len(state.plan.tool_calls) if state.plan else 0,
    )
    if state.plan is None:
        state.status = "error"
        state.errors.append("missing execution plan")
        state.add_trace("tools", "missing execution plan", "failed")
        logger.info("node=tools end status=error errors=%s", len(state.errors))
        return state

    results_by_id: dict[str, ToolResult] = {}
    for call in state.plan.tool_calls:
        logger.info("Node tools called %s id=%s", call.tool, call.id)
        logger.info("node=tools call_start id=%s tool=%s", call.id, call.tool)
        resolved_args, resolve_errors = _resolve_args(call.args, results_by_id)
        if resolve_errors:
            error = "; ".join(resolve_errors)
            result = ToolResult(
                tool_call_id=call.id,
                tool=call.tool,
                status="error",
                latency_ms=0,
                error=f"reference resolution failed: {error}",
            )
            state.tool_results.append(result)
            state.tool_dispatch_records.append(
                ToolDispatchRecord(
                    tool_call_id=call.id,
                    tool=call.tool,
                    handler_entered=False,
                    stage="reference_resolution",
                    error_code="reference_resolution_error",
                )
            )
            results_by_id[call.id] = result
            state.errors.append(f"{call.id}: {result.error}")
            logger.info(
                "node=tools call_skip id=%s resolve_errors=%s",
                call.id,
                len(resolve_errors),
            )
            continue

        fingerprint = tool_call_fingerprint(
            call.tool,
            resolved_args,
            state.plan.context,
        )
        cached = state.executed_call_fingerprints.get(fingerprint)
        if cached is not None:
            if cached.call_id != call.id:
                apply_runtime_failure(
                    state,
                    "execution_budget_error",
                    detail=(
                        "duplicate tool call fingerprint uses a different call id: "
                        f"{cached.call_id} -> {call.id}"
                    ),
                )
                break
            result = cached.result.model_copy(update={"latency_ms": 0}, deep=True)
            dispatch = ToolDispatchRecord(
                tool_call_id=call.id,
                tool=call.tool,
                handler_entered=False,
                stage="cache_reuse",
                error_code=cached.dispatch.error_code,
            )
            state.tool_results.append(result)
            state.tool_dispatch_records.append(dispatch)
            results_by_id[call.id] = result
            if result.status == "error":
                state.errors.append(
                    f"{call.id}: {result.error or 'tool execution failed'}"
                )
            continue

        def check_handler_gate() -> None:
            if failure := runtime_gate_failure(state, clock, resource="tools"):
                raise _RuntimeGateBlocked(failure)

        try:
            result, dispatch = await executor.execute(
                ToolCall(id=call.id, tool=call.tool, args=resolved_args),
                state.plan.context,
                before_handler_entered=check_handler_gate,
                on_handler_entered=(
                    state.run_budget.record_tool_call if state.run_budget else None
                ),
            )
        except _RuntimeGateBlocked as exc:
            apply_runtime_failure(state, exc.code)
            break
        state.tool_results.append(result)
        state.tool_dispatch_records.append(dispatch)
        state.executed_call_fingerprints[fingerprint] = CachedToolCall(
            call_id=call.id,
            result=result.model_copy(deep=True),
            dispatch=dispatch.model_copy(deep=True),
        )
        results_by_id[call.id] = result
        logger.info(
            "node=tools call_end id=%s tool=%s status=%s latency_ms=%s",
            call.id,
            call.tool,
            result.status,
            result.latency_ms,
        )
        if result.status == "error":
            state.errors.append(f"{call.id}: {result.error or 'tool execution failed'}")

    if state.errors:
        state.status = "error"
        state.add_trace("tools", "tool execution failed", "failed")
        logger.info(
            "node=tools end status=error results=%s errors=%s",
            len(state.tool_results),
            len(state.errors),
        )
        return state

    state.status = "ok"
    state.add_trace("tools", "tool execution completed", "completed")
    logger.info("node=tools end status=ok results=%s", len(state.tool_results))
    return state


def _resolve_args(
    value: Any,
    results_by_id: dict[str, ToolResult],
) -> tuple[Any, list[str]]:
    if isinstance(value, str) and value.startswith("$"):
        return _resolve_reference(value, results_by_id)
    if isinstance(value, dict):
        resolved: dict[str, Any] = {}
        errors: list[str] = []
        for key, item in value.items():
            resolved_item, item_errors = _resolve_args(item, results_by_id)
            resolved[key] = resolved_item
            errors.extend(item_errors)
        return resolved, errors
    if isinstance(value, list):
        resolved_items = []
        errors = []
        for item in value:
            resolved_item, item_errors = _resolve_args(item, results_by_id)
            resolved_items.append(resolved_item)
            errors.extend(item_errors)
        return resolved_items, errors
    return value, []


def _resolve_reference(
    reference: str,
    results_by_id: dict[str, ToolResult],
) -> tuple[Any, list[str]]:
    parsed = parse_reference(reference)
    if parsed is None:
        return None, [f"invalid reference: {reference}"]

    result = results_by_id.get(parsed.call_id)
    if result is None:
        return None, [f"reference target is unavailable: {reference}"]
    if result.status != "ok":
        return None, [f"reference target failed: {parsed.call_id}"]

    value, found = lookup_path(result.model_dump(mode="json"), parsed.parts[1:])
    if not found:
        return None, [f"reference path not found: {reference}"]
    return value, []
