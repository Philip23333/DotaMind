import hashlib
import json
from itertools import combinations
from typing import Any

from app.agentic.models import QueryContext
from app.agentic.runtime.models import (
    RecoveryExecutedCall,
    RecoveryFeedback,
)
from app.agentic.state import AgentRunState
from app.agentic.tools import ToolRegistry


def tool_call_fingerprint(
    tool: str,
    resolved_args: dict[str, Any],
    context: QueryContext,
) -> str:
    payload = {
        "args": resolved_args,
        "context": context.model_dump(mode="json"),
        "tool": tool,
    }
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def recoverable_missing_evidence(
    state: AgentRunState,
    registry: ToolRegistry,
) -> list[str] | None:
    """Return all missing global kinds only when unused tools can produce each."""

    graph = state.evidence_graph
    plan = state.plan
    if graph is None or plan is None or not graph.missing:
        return None

    missing = list(dict.fromkeys(graph.missing))
    effective_kinds = set(state.effective_required_evidence)
    if any(":" in kind or kind not in effective_kinds for kind in missing):
        return None

    used_tools = {call.tool for call in plan.tool_calls}
    unused = [definition for definition in registry.list() if definition.name not in used_tools]
    for kind in missing:
        if not any(kind in definition.evidence_kinds for definition in unused):
            return None
    return missing


def minimum_recovery_tool_calls(
    state: AgentRunState,
    registry: ToolRegistry,
    missing_evidence: list[str],
) -> int | None:
    if state.plan is None:
        return None
    missing = set(missing_evidence)
    used_tools = {call.tool for call in state.plan.tool_calls}
    coverages = [
        set(definition.evidence_kinds) & missing
        for definition in registry.list()
        if definition.name not in used_tools
        and set(definition.evidence_kinds) & missing
    ]
    for count in range(1, len(coverages) + 1):
        for selected in combinations(coverages, count):
            if set().union(*selected) >= missing:
                return count
    return None


def build_recovery_feedback(
    state: AgentRunState,
    missing_evidence: list[str],
    *,
    remaining_tool_budget: int,
) -> RecoveryFeedback:
    return RecoveryFeedback(
        missing_evidence=missing_evidence,
        executed_calls=[
            RecoveryExecutedCall(id=result.tool_call_id, tool=result.tool)
            for result in state.tool_results
            if result.status == "ok"
        ],
        remaining_tool_budget=remaining_tool_budget,
    )
