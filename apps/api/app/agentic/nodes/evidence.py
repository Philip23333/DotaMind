import logging

from app.agentic.evidence.graph import build_evidence_graph
from app.agentic.state import AgentRunState
from app.agentic.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)


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
