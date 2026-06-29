from app.agentic.answer import AnswerSynthesizer
from app.agentic.critic import AgenticCritic
from app.agentic.nodes import (
    answer_node,
    critic_node,
    evidence_node,
    planner_node,
    response_node,
    tool_executor_node,
    validate_plan_node,
)
from app.agentic.planner import AgenticPlanner
from app.agentic.registry import ToolExecutor, ToolRegistry
from app.agentic.state import AgentRunState


class AgentGraphRunner:
    def __init__(self, planner: AgenticPlanner, registry: ToolRegistry) -> None:
        self.planner = planner
        self.executor = ToolExecutor(registry)
        self.answer_synthesizer = AnswerSynthesizer()
        self.critic = AgenticCritic()

    async def run(self, state: AgentRunState) -> AgentRunState:
        state = await planner_node(state, self.planner)
        if state.status != "error" and state.status != "insufficient_tools":
            state = validate_plan_node(state)

        if state.status == "error":
            state = evidence_node(state)
            return response_node(state)
        if state.status == "insufficient_tools":
            return response_node(state)

        state = await tool_executor_node(state, self.executor)
        state = evidence_node(state)
        if state.status == "error":
            return response_node(state)

        state = answer_node(state, self.answer_synthesizer)
        if state.status == "error":
            return response_node(state)
        state = critic_node(state, self.critic)
        return response_node(state)
