from typing import TYPE_CHECKING

from app.agentic.runtime.models import FailureStage

if TYPE_CHECKING:
    from app.agentic.state import AgentRunState


class AgentExecutionError(Exception):
    """An unexpected runtime failure with no safe terminal response to persist."""

    failure_code = "execution_error"

    def __init__(self, stage: FailureStage = "execution") -> None:
        super().__init__("agent execution failed")
        self.stage = stage


class NodeExecutionFailure(Exception):
    """Internal wrapper carrying only the last safe state and stable node metadata."""

    def __init__(
        self,
        state: "AgentRunState",
        node: str,
        failure_stage: FailureStage,
    ) -> None:
        super().__init__("node execution failed")
        self.state = state
        self.node = node
        self.failure_stage = failure_stage
