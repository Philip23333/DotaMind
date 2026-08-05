"""PlanService: the stateless v2.5 LLM Controller use case.

The public ``/plan`` debug endpoints call :meth:`run` without session metadata.
Durable multi-turn execution belongs to ``ChatRunExecutor``.
"""

from dataclasses import dataclass
from typing import Any, Literal
from uuid import UUID

from app.agentic.conversation.summary import (
    build_session_failure_turn,
    build_turn_summary,
)
from app.agentic.graph import AgentGraphRunner
from app.agentic.planning.contracts import validate_registry_contracts
from app.agentic.planning.controller import AgentController
from app.agentic.state import AgentRunState
from app.agentic.tools.stratz_tools import build_default_tool_registry
from app.core.config import get_policy, get_settings


@dataclass(frozen=True)
class PlanServiceResult:
    """Public result plus the fresh internal state when a Graph was executed."""

    public_response: dict[str, Any]
    state: AgentRunState | None
    idempotency_status: Literal["disabled", "executed", "replayed"]


class PlanService:
    """Experimental v2.5 LLM Controller use case. No legacy fallback."""

    def __init__(
        self,
        controller: AgentController | None = None,
    ) -> None:
        settings = get_settings()
        policy = get_policy()
        self.registry = build_default_tool_registry(settings)
        registry_errors = validate_registry_contracts(self.registry)
        if registry_errors:
            raise RuntimeError(
                "invalid tool registry contracts: " + "; ".join(registry_errors)
            )
        self.controller = controller or AgentController(self.registry)
        # Compile graph once; AgentGraphRunner.run() is concurrency-safe across
        # sessions because executor/critic/synthesizer carry no per-request state.
        self.runner = AgentGraphRunner(
            self.controller,
            self.registry,
            runtime_policy=policy.planning.runtime,
        )
        self._conv_policy = policy.conversation

    async def run(self, query: str, game: str = "dota2") -> PlanServiceResult:
        """Run one stateless planning turn for the debug console."""
        state = AgentRunState(query=query, game=game)
        result = await self.runner.run(state)
        return PlanServiceResult(
            public_response=self._public_response(result, session_id=None),
            state=result,
            idempotency_status="disabled",
        )

    def _build_turn(self, result: AgentRunState):
        if result.safe_failure_required:
            return build_session_failure_turn(
                result,
                max_query_chars=self._conv_policy.turn_query_max_chars,
            )
        return build_turn_summary(
            result,
            max_summary_chars=self._conv_policy.answer_summary_max_chars,
            max_query_chars=self._conv_policy.turn_query_max_chars,
        )

    @staticmethod
    def _public_response(
        result: AgentRunState,
        *,
        session_id: UUID | None,
    ) -> dict[str, Any]:
        if result.response is None:
            raise RuntimeError("Graph completed without a public response")
        response = dict(result.response)
        response["session_id"] = str(session_id) if session_id is not None else None
        return response
