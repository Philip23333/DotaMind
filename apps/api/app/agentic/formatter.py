from typing import Any

from app.agentic.state import AgentRunState


class PlanFormatter:
    """Deterministic API envelope formatter for v2.5 plan runs."""

    def format(self, state: AgentRunState) -> dict[str, Any]:
        return state.model_dump(
            mode="json",
            include={
                "query",
                "game",
                "status",
                "reason",
                "plan",
                "tool_results",
                "evidence_graph",
                "answer",
                "review",
                "errors",
                "trace",
            },
        )
