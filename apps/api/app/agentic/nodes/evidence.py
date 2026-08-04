from app.agentic.evidence.graph import build_evidence_graph
from app.agentic.state import AgentRunState
from app.agentic.tools.registry import ToolRegistry


def evidence_node(state: AgentRunState, registry: ToolRegistry) -> AgentRunState:
    state.add_trace("evidence", "build evidence graph", "planned")
    if state.plan is None:
        state.status = "error"
        state.errors.append("missing execution plan for evidence construction")
        state.add_trace("evidence", "missing execution plan", "failed")
        return state

    state.evidence_graph = build_evidence_graph(
        state.plan,
        state.tool_results,
        registry,
        required_evidence=state.effective_required_evidence,
        global_required_evidence=state.global_required_evidence,
        mandatory_evidence_by_call=state.mandatory_evidence_by_call,
    )
    state.add_trace("evidence", "evidence graph completed", "completed")
    return state
