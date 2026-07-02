import logging
from typing import Any

from app.agentic.models import ToolCall, ToolResult
from app.agentic.references import lookup_path, parse_reference
from app.agentic.state import AgentRunState
from app.agentic.tools.executor import ToolExecutor

logger = logging.getLogger(__name__)


async def tool_executor_node(
    state: AgentRunState,
    executor: ToolExecutor,
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
            state.errors.extend(f"{call.id}: {error}" for error in resolve_errors)
            logger.info(
                "node=tools call_skip id=%s resolve_errors=%s",
                call.id,
                len(resolve_errors),
            )
            continue

        result = await executor.execute(
            ToolCall(id=call.id, tool=call.tool, args=resolved_args),
            state.plan.context,
        )
        state.tool_results.append(result)
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
