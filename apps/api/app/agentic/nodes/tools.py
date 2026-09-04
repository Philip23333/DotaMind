import logging
from typing import Any, Literal

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
from app.agentic.runtime.streaming import (
    ObserverStreamEvent,
    ToolStreamEvent,
    observer_events_enabled,
    publish_observer_event,
    publish_stream_event,
)
from app.agentic.state import AgentRunState
from app.agentic.tools.executor import ToolExecutor
from app.observability import emit_event

logger = logging.getLogger(__name__)


class _RuntimeGateBlocked(RuntimeError):
    def __init__(self, code: RuntimeFailureCode) -> None:
        self.code = code
        super().__init__(code)


def _public_tool_failure_code(error_code: str | None, status: str) -> str | None:
    if status != "error":
        return None
    return {
        "reference_resolution_error": "reference_resolution_error",
        "input_validation_error": "validation_error",
        "handler_error": "handler_error",
        "tool_not_registered": "tool_error",
    }.get(error_code, "tool_error")


async def tool_executor_node(
    state: AgentRunState,
    executor: ToolExecutor,
    clock: Clock,
) -> AgentRunState:
    state.add_trace("tools", "execute planned tool calls", "planned")
    if state.plan is None:
        state.status = "error"
        state.errors.append("missing execution plan")
        state.add_trace("tools", "missing execution plan", "failed")
        return state

    results_by_id: dict[str, ToolResult] = {}
    for call in state.plan.tool_calls:
        resolved_args, resolve_errors = _resolve_args(call.args, results_by_id)
        _publish_tool_observation(
            state,
            call,
            "tool_input",
            {
                "planned_args": call.args,
                "resolved_args": resolved_args,
                "resolution_errors": resolve_errors,
            },
        )
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
            state.add_trace(
                "tools",
                "tool_call",
                "failed",
                tool_call_id=call.id,
                tool=call.tool,
                failure_code="tool_error",
            )
            emit_event(
                logger,
                "tool_call_failed",
                status="error",
                tool_name=call.tool,
                tool_call_id=call.id,
                reused=False,
                failure_code="tool_error",
            )
            publish_stream_event(
                ToolStreamEvent(
                    tool_call_id=call.id,
                    tool=call.tool,
                    attempt_index=state.attempt_index,
                    status="error",
                    latency_ms=0,
                    reused=False,
                    failure_code="reference_resolution_error",
                    handler_entered=False,
                    dispatch_stage="reference_resolution",
                )
            )
            _publish_tool_observation(
                state,
                call,
                "tool_output",
                {"result": result.model_dump(mode="json")},
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
            result = cached.result.model_copy(deep=True)
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
            state.add_trace(
                "tools",
                "tool_call",
                "completed" if result.status == "ok" else "failed",
                tool_call_id=call.id,
                tool=call.tool,
                reused=True,
                failure_code="tool_error" if result.status == "error" else None,
            )
            emit_event(
                logger,
                "tool_call_reused",
                status=result.status,
                tool_name=call.tool,
                tool_call_id=call.id,
                reused=True,
                failure_code="tool_error" if result.status == "error" else None,
            )
            publish_stream_event(
                ToolStreamEvent(
                    tool_call_id=call.id,
                    tool=call.tool,
                    attempt_index=state.attempt_index,
                    status=result.status,
                    latency_ms=0,
                    reused=True,
                    failure_code=_public_tool_failure_code(dispatch.error_code, result.status),
                    handler_entered=dispatch.handler_entered,
                    dispatch_stage=dispatch.stage,
                )
            )
            _publish_tool_observation(
                state,
                call,
                "tool_output",
                {"result": result.model_dump(mode="json"), "reused": True},
            )
            continue

        def check_handler_gate() -> None:
            if failure := runtime_gate_failure(state, clock, resource="tools"):
                raise _RuntimeGateBlocked(failure)

        def on_handler_entered(
            tool_call_id: str = call.id,
            tool_name: str = call.tool,
            attempt_index: int = state.attempt_index,
        ) -> None:
            if state.run_budget is not None:
                state.run_budget.record_tool_call()
            publish_stream_event(
                ToolStreamEvent(
                    tool_call_id=tool_call_id,
                    tool=tool_name,
                    attempt_index=attempt_index,
                    status="running",
                    reused=False,
                    handler_entered=True,
                    dispatch_stage="handler",
                )
            )

        try:
            result, dispatch = await executor.execute(
                ToolCall(id=call.id, tool=call.tool, args=resolved_args),
                state.plan.context,
                before_handler_entered=check_handler_gate,
                on_handler_entered=on_handler_entered,
            )
        except _RuntimeGateBlocked as exc:
            publish_stream_event(
                ToolStreamEvent(
                    tool_call_id=call.id,
                    tool=call.tool,
                    attempt_index=state.attempt_index,
                    status="error",
                    latency_ms=0,
                    reused=False,
                    failure_code=exc.code,
                    handler_entered=False,
                    dispatch_stage="pre_dispatch",
                )
            )
            _publish_tool_observation(
                state,
                call,
                "tool_output",
                {
                    "result": None,
                    "failure_code": exc.code,
                    "dispatch_stage": "pre_dispatch",
                },
            )
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
        state.add_trace(
            "tools",
            "tool_call",
            "completed" if result.status == "ok" else "failed",
            tool_call_id=call.id,
            tool=call.tool,
            reused=False,
            failure_code="tool_error" if result.status == "error" else None,
        )
        emit_event(
            logger,
            "tool_call_completed" if result.status == "ok" else "tool_call_failed",
            status=result.status,
            tool_name=call.tool,
            tool_call_id=call.id,
            reused=False,
            failure_code="tool_error" if result.status == "error" else None,
        )
        publish_stream_event(
            ToolStreamEvent(
                tool_call_id=call.id,
                tool=call.tool,
                attempt_index=state.attempt_index,
                status=result.status,
                latency_ms=result.latency_ms,
                reused=False,
                failure_code=_public_tool_failure_code(dispatch.error_code, result.status),
                handler_entered=dispatch.handler_entered,
                dispatch_stage=dispatch.stage,
            )
        )
        _publish_tool_observation(
            state,
            call,
            "tool_output",
            {
                "result": result.model_dump(mode="json"),
                "reused": False,
                "dispatch": dispatch.model_dump(mode="json"),
            },
        )
        if result.status == "error":
            state.errors.append(f"{call.id}: {result.error or 'tool execution failed'}")

    if state.status == "waiting_input":
        return state
    if state.errors:
        state.status = "error"
        state.add_trace("tools", "tool execution failed", "failed")
        return state

    state.status = "ok"
    state.add_trace("tools", "tool execution completed", "completed")
    return state


def _publish_tool_observation(
    state: AgentRunState,
    call: ToolCall,
    kind: Literal["tool_input", "tool_output"],
    payload: dict[str, Any],
) -> None:
    if not observer_events_enabled():
        return
    publish_observer_event(
        ObserverStreamEvent(
            kind=kind,
            stage="tool",
            call_id=call.id,
            name=call.tool,
            attempt_index=state.attempt_index,
            payload=payload,
        )
    )


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
