from app.agentic.planning.decisions import ControllerDecision, ToolPlanDecision
from app.agentic.runtime.models import RecoveryFeedback
from app.agentic.tools import ToolRegistry


def validate_replan_decision(
    decision: ControllerDecision,
    baseline: ToolPlanDecision,
    feedback: RecoveryFeedback,
    registry: ToolRegistry,
    *,
    remaining_tool_budget: int,
) -> list[str]:
    if not isinstance(decision, ToolPlanDecision):
        return ["replan must return a complete tool_plan decision"]

    errors: list[str] = []
    original = baseline.plan
    candidate = decision.plan
    for field in ("intent", "goal", "output_contract", "context", "constraints"):
        if getattr(candidate, field) != getattr(original, field):
            errors.append(f"replan must preserve plan.{field}")

    if sorted(set(candidate.required_evidence)) != sorted(
        set(original.required_evidence)
    ):
        errors.append("replan must preserve required_evidence exactly")

    prefix_size = len(original.tool_calls)
    if candidate.tool_calls[:prefix_size] != original.tool_calls:
        errors.append("replan must preserve prior tool calls as an exact prefix")
    appended = candidate.tool_calls[prefix_size:]
    if not appended:
        errors.append("replan must append at least one tool call")
    if len(appended) > remaining_tool_budget:
        errors.append("replan appended tool calls exceed remaining run tool budget")

    old_ids = {call.id for call in original.tool_calls}
    if any(call.id in old_ids for call in appended):
        errors.append("replan appended tool call ids must be new")
    old_tools = {call.tool for call in original.tool_calls}
    if repeated_tools := sorted({call.tool for call in appended} & old_tools):
        errors.append(
            "replan must append previously unused tools: " + ", ".join(repeated_tools)
        )

    registered = {definition.name: definition for definition in registry.list()}
    relevant_kinds = set(feedback.missing_evidence)
    irrelevant_tools = sorted(
        {
            call.tool
            for call in appended
            if call.tool in registered
            and not (set(registered[call.tool].evidence_kinds) & relevant_kinds)
        }
    )
    if irrelevant_tools:
        errors.append(
            "replan appended tools must produce missing evidence: "
            + ", ".join(irrelevant_tools)
        )
    produced = {
        kind
        for call in appended
        if call.tool in registered
        for kind in registered[call.tool].evidence_kinds
    }
    uncovered = sorted(relevant_kinds - produced)
    if uncovered:
        errors.append(
            "replan appended tools do not cover missing evidence: "
            + ", ".join(uncovered)
        )
    return errors
