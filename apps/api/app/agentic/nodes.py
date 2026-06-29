import logging
from typing import Any

from app.agentic.answer import AnswerSynthesizer
from app.agentic.contracts import get_contract
from app.agentic.critic import AgenticCritic
from app.agentic.evidence import build_evidence_graph
from app.agentic.models import ToolCall, ToolResult
from app.agentic.planner import AgenticPlanner
from app.agentic.registry import ToolExecutor, ToolRegistry
from app.agentic.state import AgentRunState

logger = logging.getLogger(__name__)


async def planner_node(state: AgentRunState, planner: AgenticPlanner) -> AgentRunState:
    state.add_trace("planner", "create execution plan", "planned")
    logger.info("node=planner start query_chars=%s game=%s", len(state.query), state.game)
    planning = await planner.plan(state.query, state.game)
    state.planning = planning
    state.plan = planning.plan
    state.reason = planning.reason
    if planning.status != "planned" or planning.plan is None:
        state.status = planning.status
        state.errors = planning.errors
        state.add_trace("planner", planning.reason or planning.status, planning.status)
        logger.info(
            "node=planner end status=%s reason=%s errors=%s",
            state.status,
            state.reason,
            len(state.errors),
        )
        return state

    state.add_trace("planner", planning.reason or "plan accepted", "completed")
    state.status = "ok"
    logger.info(
        "node=planner end status=planned intent=%s tools=%s required_evidence=%s",
        planning.plan.intent,
        len(planning.plan.tool_calls),
        len(planning.plan.required_evidence),
    )
    return state


def validate_plan_node(state: AgentRunState) -> AgentRunState:
    state.add_trace("validate", "validate execution plan", "planned")
    logger.info("node=validate start has_plan=%s", state.plan is not None)
    plan = state.plan
    if plan is None:
        state.status = "error"
        state.errors.append("missing execution plan")
        state.add_trace("validate", "missing execution plan", "failed")
        logger.info("node=validate end status=error errors=%s", len(state.errors))
        return state

    errors = []
    if len(plan.tool_calls) > plan.constraints.max_tool_calls:
        errors.append(
            "plan exceeds max_tool_calls "
            f"({len(plan.tool_calls)} > {plan.constraints.max_tool_calls})"
        )

    seen = set()
    for call in plan.tool_calls:
        if call.id in seen:
            errors.append(f"duplicate tool call id: {call.id}")
        seen.add(call.id)

    if errors:
        state.status = "error"
        state.errors.extend(errors)
        state.add_trace("validate", "plan validation failed", "failed")
        logger.info("node=validate end status=error errors=%s", len(state.errors))
        return state

    state.status = "ok"
    state.add_trace("validate", "plan validation completed", "completed")
    logger.info("node=validate end status=ok tools=%s", len(plan.tool_calls))
    return state


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
            ToolCall(id=call.id, tool=call.tool, args=resolved_args)
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


def evidence_node(state: AgentRunState, registry: ToolRegistry) -> AgentRunState:
    state.add_trace("evidence", "build evidence graph", "planned")
    logger.info("node=evidence start tool_results=%s", len(state.tool_results))
    if state.plan is None:
        state.add_trace("evidence", "missing execution plan", "failed")
        logger.info("node=evidence end status=failed missing_plan=true")
        return state

    state.evidence_graph = build_evidence_graph(
        state.plan,
        state.tool_results,
        registry,
    )
    state.add_trace("evidence", "evidence graph completed", "completed")
    logger.info(
        "node=evidence end evidence=%s missing=%s completeness=%.2f",
        len(state.evidence_graph.evidence),
        len(state.evidence_graph.missing),
        state.evidence_graph.data_quality.completeness,
    )
    return state


async def answer_node(
    state: AgentRunState,
    synthesizer: AnswerSynthesizer,
) -> AgentRunState:
    state.add_trace("answer", "synthesize structured answer", "planned")
    structured_contract = (
        state.plan is not None
        and (contract := get_contract(state.plan.output_contract)) is not None
        and contract.structured
    )
    logger.info(
        "node=answer start has_graph=%s structured_contract=%s output_contract=%s",
        state.evidence_graph is not None,
        structured_contract,
        state.plan.output_contract if state.plan else None,
    )
    if state.plan is None or state.evidence_graph is None:
        state.status = "error"
        state.errors.append("missing plan or evidence graph for answer synthesis")
        state.add_trace("answer", "missing answer inputs", "failed")
        logger.info("node=answer end status=error errors=%s", len(state.errors))
        return state

    state.answer = await synthesizer.synthesize(state.plan, state.evidence_graph)
    state.add_trace("answer", f"answer status: {state.answer.status}", "completed")
    logger.info(
        "node=answer end status=%s recommendations=%s confidence=%.2f",
        state.answer.status,
        len(state.answer.recommendations),
        state.answer.confidence,
    )
    return state


def critic_node(state: AgentRunState, critic: AgenticCritic) -> AgentRunState:
    state.add_trace("critic", "review plan evidence and answer", "planned")
    logger.info("node=critic start has_answer=%s", state.answer is not None)
    if state.plan is None or state.evidence_graph is None or state.answer is None:
        state.status = "error"
        state.errors.append("missing critic inputs")
        state.add_trace("critic", "missing critic inputs", "failed")
        logger.info("node=critic end status=error errors=%s", len(state.errors))
        return state

    state.review = critic.review(state.plan, state.evidence_graph, state.answer)
    state.add_trace(
        "critic",
        f"review severity: {state.review.severity}",
        state.review.severity,
    )
    logger.info(
        "node=critic end severity=%s reasons=%s passed=%s",
        state.review.severity,
        len(state.review.reasons),
        state.review.passed,
    )
    return state


def response_node(state: AgentRunState) -> AgentRunState:
    state.response_type = _response_type(state)
    logger.info(
        "node=response start status=%s type=%s errors=%s has_answer=%s has_review=%s",
        state.status,
        state.response_type,
        len(state.errors),
        state.answer is not None,
        state.review is not None,
    )
    state.response = state.model_dump(
        mode="json",
        include={
            "query",
            "game",
            "status",
            "reason",
            "response_type",
            "plan",
            "tool_results",
            "evidence_graph",
            "answer",
            "review",
            "errors",
            "trace",
        },
    )
    logger.info("node=response end response_ready=true")
    return state


def _response_type(state: AgentRunState) -> str:
    if state.status == "insufficient_tools":
        return "capability_boundary"
    if state.status == "error":
        return "execution_error"
    if state.answer is None:
        return "raw_tool_results"
    if state.answer.status == "insufficient_evidence":
        return "insufficient_evidence"
    if state.answer.status == "error":
        return "answer_error"
    contract = get_contract(state.answer.answer_type)
    if state.answer.status == "ok" and contract is not None:
        return state.answer.answer_type
    if state.answer.status == "unsupported_output_contract":
        return "unsupported_answer"
    return "raw_tool_results"


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
    parts = reference.removeprefix("$").split(".")
    if len(parts) < 2:
        return None, [f"invalid reference: {reference}"]

    call_id = parts[0]
    result = results_by_id.get(call_id)
    if result is None:
        return None, [f"reference target is unavailable: {reference}"]
    if result.status != "ok":
        return None, [f"reference target failed: {call_id}"]

    current: Any = result.model_dump(mode="json")
    for part in parts[1:]:
        if isinstance(current, dict) and part in current:
            current = current[part]
            continue
        return None, [f"reference path not found: {reference}"]
    return current, []
