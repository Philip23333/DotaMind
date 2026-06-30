from app.agentic.graph import AgentGraphRunner
from app.agentic.planning.planner import AgenticPlanner
from app.agentic.state import AgentRunState
from app.agentic.tools.stratz_tools import build_default_tool_registry
from app.core.config import get_settings


class PlanService:
    """Experimental v2.5 LLM planner use case. No fallback to legacy pipeline."""

    def __init__(self, planner: AgenticPlanner | None = None) -> None:
        self.registry = build_default_tool_registry(get_settings())
        self.planner = planner or AgenticPlanner(self.registry)

    async def run(self, query: str, game: str = "dota2") -> AgentRunState:
        return await AgentGraphRunner(self.planner, self.registry).run(
            AgentRunState(query=query, game=game)
        )
