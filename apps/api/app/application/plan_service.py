"""PlanService: v2.5 LLM planner use case.

No fallback to legacy pipeline. Session memory is opt-in via session_id;
omitting it preserves the original stateless single-turn behaviour.
"""

import logging
from uuid import UUID

from app.agentic.conversation.summary import (
    build_session_failure_turn,
    build_turn_summary,
)
from app.agentic.graph import AgentGraphRunner
from app.agentic.planning.planner import AgenticPlanner
from app.agentic.state import AgentRunState
from app.agentic.tools.stratz_tools import build_default_tool_registry
from app.application.session_store import InMemorySessionStore, SessionStore
from app.core.config import get_policy, get_settings

logger = logging.getLogger(__name__)


class PlanService:
    """Experimental v2.5 LLM planner use case. No fallback to legacy pipeline."""

    def __init__(
        self,
        planner: AgenticPlanner | None = None,
        session_store: SessionStore | None = None,
    ) -> None:
        settings = get_settings()
        policy = get_policy()
        self.registry = build_default_tool_registry(settings)
        self.planner = planner or AgenticPlanner(self.registry)
        # Compile graph once; AgentGraphRunner.run() is concurrency-safe across
        # sessions because executor/critic/synthesizer carry no per-request state.
        self.runner = AgentGraphRunner(self.planner, self.registry)
        self.session_store: SessionStore = session_store or InMemorySessionStore(
            max_sessions=policy.conversation.max_sessions,
            max_turns_per_session=policy.conversation.max_turns_per_session,
        )
        self._conv_policy = policy.conversation

    async def run(
        self,
        query: str,
        game: str = "dota2",
        session_id: UUID | None = None,
    ) -> AgentRunState:
        """Run one planning turn, optionally within a persistent session.

        When session_id is None the service is stateless: no history is read
        or written, behaviour is identical to the original single-turn design.

        When session_id is provided the service:
        1. Acquires the per-session lock (serialises concurrent requests).
        2. Reads the most-recent ``history_window`` turns from the store.
        3. Runs the graph with history injected into AgentRunState.
        4. Appends a compact turn summary back to the store.

        Phase 1 limitation: the session lock is per-process only.
        Multi-worker deployments require a distributed lock (Phase 2, Redis).
        """
        if session_id is None:
            # Stateless path — 100% backward-compatible with pre-session API.
            state = AgentRunState(query=query, game=game)
            return await self.runner.run(state)

        sid = str(session_id)
        async with self.session_store.transaction(sid):
            history = await self.session_store.get(
                sid, limit=self._conv_policy.history_window
            )
            logger.info(
                "plan_service session=%s history_turns=%s", sid[:8], len(history)
            )
            state = AgentRunState(
                query=query,
                game=game,
                history=history,
                session_memory_enabled=True,
            )
            result = await self.runner.run(state)
            if result.response_type == "session_request_failed":
                turn = build_session_failure_turn(
                    result,
                    max_query_chars=self._conv_policy.turn_query_max_chars,
                )
            else:
                turn = build_turn_summary(
                    result,
                    max_summary_chars=self._conv_policy.answer_summary_max_chars,
                    max_query_chars=self._conv_policy.turn_query_max_chars,
                )
            stored = await self.session_store.append(sid, turn)
            logger.info(
                "plan_service session=%s turn_index=%s status=%s",
                sid[:8],
                stored.turn_index,
                stored.status,
            )

        return result
