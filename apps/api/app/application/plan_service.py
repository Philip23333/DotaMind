"""PlanService: v2.5 LLM Controller use case.

No fallback to legacy pipeline. Session memory is opt-in via session_id;
omitting it preserves the original stateless single-turn behaviour.
"""

import logging
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
from app.application.idempotency import (
    IdempotencyConflictError,
    build_request_hash,
)
from app.application.session_store import InMemorySessionStore, SessionStore
from app.core.config import get_policy, get_settings

logger = logging.getLogger(__name__)


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
        session_store: SessionStore | None = None,
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
        self.session_store: SessionStore = session_store or InMemorySessionStore(
            max_sessions=policy.conversation.max_sessions,
            max_turns_per_session=policy.conversation.max_turns_per_session,
            request_record_ttl_seconds=policy.conversation.request_record_ttl_seconds,
            max_request_records_per_session=(
                policy.conversation.max_request_records_per_session
            ),
        )
        self._conv_policy = policy.conversation

    async def run(
        self,
        query: str,
        game: str = "dota2",
        session_id: UUID | None = None,
        request_id: UUID | None = None,
    ) -> PlanServiceResult:
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
        if request_id is not None and session_id is None:
            raise ValueError("request_id requires session_id")

        if session_id is None:
            # Stateless path — 100% backward-compatible with pre-session API.
            state = AgentRunState(query=query, game=game)
            result = await self.runner.run(state)
            return PlanServiceResult(
                public_response=self._public_response(result, session_id=None),
                state=result,
                idempotency_status="disabled",
            )

        sid = str(session_id)
        async with self.session_store.transaction(sid):
            if request_id is not None:
                request_begin = await self.session_store.begin_request(
                    sid,
                    request_id,
                    build_request_hash(query=query, game=game),
                )
                if request_begin.action == "replay":
                    assert request_begin.cached_public_response is not None
                    return PlanServiceResult(
                        public_response=request_begin.cached_public_response,
                        state=None,
                        idempotency_status="replayed",
                    )
                if request_begin.action == "conflict":
                    raise IdempotencyConflictError(
                        query=query,
                        game=game,
                        session_id=sid,
                    )
                assert request_begin.owner_token is not None
                return await self._execute_idempotent_stateful_request(
                    sid=sid,
                    session_id=session_id,
                    request_id=request_id,
                    owner_token=request_begin.owner_token,
                    query=query,
                    game=game,
                )

            return await self._execute_stateful_request(
                sid=sid,
                session_id=session_id,
                query=query,
                game=game,
            )

    async def _execute_stateful_request(
        self,
        *,
        sid: str,
        session_id: UUID,
        query: str,
        game: str,
    ) -> PlanServiceResult:
        history = await self.session_store.get(
            sid, limit=self._conv_policy.history_window
        )
        logger.info("plan_service session=%s history_turns=%s", sid[:8], len(history))
        state = AgentRunState(
            query=query,
            game=game,
            history=history,
            session_memory_enabled=True,
            internal_session_id=session_id,
        )
        result = await self.runner.run(state)
        stored = await self.session_store.append(sid, self._build_turn(result))
        logger.info(
            "plan_service session=%s turn_index=%s status=%s",
            sid[:8],
            stored.turn_index,
            stored.status,
        )
        return PlanServiceResult(
            public_response=self._public_response(result, session_id=session_id),
            state=result,
            idempotency_status="disabled",
        )

    async def _execute_idempotent_stateful_request(
        self,
        *,
        sid: str,
        session_id: UUID,
        request_id: UUID,
        owner_token: UUID,
        query: str,
        game: str,
    ) -> PlanServiceResult:
        try:
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
                internal_session_id=session_id,
                internal_request_id=request_id,
            )
            result = await self.runner.run(state)
            public_response = self._public_response(result, session_id=session_id)
            if result.run_context is None:
                raise RuntimeError("idempotent request completed without a run context")
            stored = await self.session_store.complete_request_with_turn(
                sid,
                request_id,
                owner_token,
                self._build_turn(result),
                public_response,
                result.run_context.run_id,
            )
            logger.info(
                "plan_service session=%s turn_index=%s status=%s",
                sid[:8],
                stored.turn_index,
                stored.status,
            )
            return PlanServiceResult(
                public_response=public_response,
                state=result,
                idempotency_status="executed",
            )
        except BaseException:
            await self.session_store.fail_request(sid, request_id, owner_token)
            raise

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
