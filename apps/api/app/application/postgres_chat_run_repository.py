"""PostgreSQL repository for durable background chat Run lifecycle state."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import and_, or_, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agentic.conversation.models import Turn
from app.application.chat_run_repository import (
    ACTIVE_RUN_STATUSES,
    ChatRunActiveError,
    ChatRunCancelResult,
    ChatRunCreateResult,
    ChatRunFencingLostError,
    ChatRunIdempotencyConflictError,
    ChatRunNotFoundError,
    ChatRunRepositoryError,
    ChatRunStateError,
    ChatRunStatus,
    ChatRunSummary,
    ChatRunTerminalError,
)
from app.application.postgres_chat_repository import browser_id_hash
from app.persistence.models import ChatRunRow, ChatSessionRow, ChatTurnRow


def _summary(row: ChatRunRow) -> ChatRunSummary:
    return ChatRunSummary(
        run_id=row.id,
        session_id=row.session_id,
        request_id=row.request_id,
        payload_hash=row.payload_hash,
        user_query=row.user_query,
        status=row.status,  # type: ignore[arg-type]
        fencing_token=row.fencing_token,
        worker_id=row.worker_id,
        last_event_sequence=row.last_event_sequence,
        result_turn_id=row.result_turn_id,
        error_code=row.error_code,
        created_at=row.created_at,
        started_at=row.started_at,
        heartbeat_at=row.heartbeat_at,
        cancel_requested_at=row.cancel_requested_at,
        completed_at=row.completed_at,
    )


class PostgresChatRunRepository:
    """Repository whose rows are the authoritative Run lifecycle state."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def create_or_get_run(
        self,
        *,
        browser_id: str,
        session_id: UUID,
        request_id: UUID,
        payload_hash: str,
        user_query: str,
        run_id: UUID,
    ) -> ChatRunCreateResult:
        browser_hash = browser_id_hash(browser_id)
        now = datetime.now(UTC)
        try:
            async with self._session_factory.begin() as session:
                owner = await session.scalar(
                    select(ChatSessionRow)
                    .where(
                        ChatSessionRow.id == session_id,
                        ChatSessionRow.browser_id_hash == browser_hash,
                    )
                    .with_for_update()
                )
                if owner is None:
                    raise ChatRunNotFoundError()

                existing = await session.scalar(
                    select(ChatRunRow)
                    .where(
                        ChatRunRow.session_id == session_id,
                        ChatRunRow.request_id == request_id,
                    )
                    .with_for_update()
                )
                if existing is not None:
                    if existing.payload_hash != payload_hash:
                        raise ChatRunIdempotencyConflictError()
                    return ChatRunCreateResult(action="replayed", run=_summary(existing))

                active = await session.scalar(
                    select(ChatRunRow.id).where(
                        ChatRunRow.session_id == session_id,
                        ChatRunRow.status.in_(ACTIVE_RUN_STATUSES),
                    )
                )
                if active is not None:
                    raise ChatRunActiveError()

                row = ChatRunRow(
                    id=run_id,
                    session_id=session_id,
                    request_id=request_id,
                    payload_hash=payload_hash,
                    user_query=user_query,
                    status="queued",
                    last_event_sequence=0,
                    created_at=now,
                )
                session.add(row)
                await session.flush()
                return ChatRunCreateResult(action="created", run=_summary(row))
        except (
            ChatRunActiveError,
            ChatRunIdempotencyConflictError,
            ChatRunNotFoundError,
            ChatRunRepositoryError,
        ):
            raise
        except SQLAlchemyError as exc:
            raise ChatRunRepositoryError() from exc

    async def get_run_for_browser(self, browser_id: str, run_id: UUID) -> ChatRunSummary:
        try:
            async with self._session_factory() as session:
                row = await self._owned_run(session, browser_id, run_id)
        except ChatRunNotFoundError:
            raise
        except SQLAlchemyError as exc:
            raise ChatRunRepositoryError() from exc
        return _summary(row)

    async def get_active_run(
        self, browser_id: str, session_id: UUID
    ) -> ChatRunSummary | None:
        try:
            async with self._session_factory() as session:
                owner = await session.scalar(
                    select(ChatSessionRow.id).where(
                        ChatSessionRow.id == session_id,
                        ChatSessionRow.browser_id_hash == browser_id_hash(browser_id),
                    )
                )
                if owner is None:
                    raise ChatRunNotFoundError()
                row = await session.scalar(
                    select(ChatRunRow)
                    .where(
                        ChatRunRow.session_id == session_id,
                        ChatRunRow.status.in_(ACTIVE_RUN_STATUSES),
                    )
                    .order_by(ChatRunRow.created_at.desc())
                )
        except ChatRunNotFoundError:
            raise
        except SQLAlchemyError as exc:
            raise ChatRunRepositoryError() from exc
        return _summary(row) if row is not None else None

    async def mark_running(
        self, *, browser_id: str, run_id: UUID, worker_id: str, fencing_token: int
    ) -> ChatRunSummary:
        now = datetime.now(UTC)
        try:
            async with self._session_factory.begin() as session:
                row = await self._owned_run(session, browser_id, run_id, lock=True)
                if row.status == "queued":
                    row.status = "running"
                    row.worker_id = worker_id
                    row.fencing_token = fencing_token
                    row.started_at = now
                    row.heartbeat_at = now
                elif row.status == "running":
                    if row.worker_id != worker_id or row.fencing_token != fencing_token:
                        raise ChatRunStateError("run_owned_by_other_worker")
                elif row.status == "cancel_requested":
                    raise ChatRunStateError("cancel_requested")
                else:
                    raise ChatRunTerminalError()
                return _summary(row)
        except (
            ChatRunNotFoundError,
            ChatRunRepositoryError,
            ChatRunStateError,
            ChatRunTerminalError,
        ):
            raise
        except SQLAlchemyError as exc:
            raise ChatRunRepositoryError() from exc

    async def update_heartbeat(self, *, run_id: UUID, worker_id: str) -> ChatRunSummary:
        now = datetime.now(UTC)
        try:
            async with self._session_factory.begin() as session:
                row = await session.scalar(
                    select(ChatRunRow).where(ChatRunRow.id == run_id).with_for_update()
                )
                if row is None:
                    raise ChatRunNotFoundError()
                if row.worker_id != worker_id:
                    raise ChatRunStateError("run_owned_by_other_worker")
                if row.status not in ACTIVE_RUN_STATUSES:
                    raise ChatRunTerminalError()
                row.heartbeat_at = now
                return _summary(row)
        except (
            ChatRunNotFoundError,
            ChatRunRepositoryError,
            ChatRunStateError,
            ChatRunTerminalError,
        ):
            raise
        except SQLAlchemyError as exc:
            raise ChatRunRepositoryError() from exc

    async def request_cancel(
        self, *, browser_id: str, run_id: UUID
    ) -> ChatRunCancelResult:
        now = datetime.now(UTC)
        try:
            async with self._session_factory.begin() as session:
                row = await self._owned_run(session, browser_id, run_id, lock=True)
                if row.status == "cancel_requested":
                    return ChatRunCancelResult(action="already_requested", run=_summary(row))
                if row.status in {"completed", "failed", "cancelled", "interrupted"}:
                    raise ChatRunTerminalError()
                row.status = "cancel_requested"
                row.cancel_requested_at = now
                row.heartbeat_at = now
                return ChatRunCancelResult(action="requested", run=_summary(row))
        except (
            ChatRunNotFoundError,
            ChatRunRepositoryError,
            ChatRunStateError,
            ChatRunTerminalError,
        ):
            raise
        except SQLAlchemyError as exc:
            raise ChatRunRepositoryError() from exc

    async def mark_cancelled(
        self, *, run_id: UUID, worker_id: str | None = None
    ) -> ChatRunSummary:
        return await self._mark_terminal(
            run_id=run_id,
            status="cancelled",
            error_code=None,
            worker_id=worker_id,
            allowed_statuses={"cancel_requested"},
        )

    async def mark_failed(
        self, *, run_id: UUID, error_code: str, worker_id: str | None = None
    ) -> ChatRunSummary:
        return await self._mark_terminal(
            run_id=run_id,
            status="failed",
            error_code=error_code,
            worker_id=worker_id,
            allowed_statuses={"queued", "running"},
        )

    async def mark_interrupted(
        self, *, run_id: UUID, error_code: str, worker_id: str | None = None
    ) -> ChatRunSummary:
        return await self._mark_terminal(
            run_id=run_id,
            status="interrupted",
            error_code=error_code,
            worker_id=worker_id,
            allowed_statuses=set(ACTIVE_RUN_STATUSES),
        )

    async def interrupt_stale_runs(
        self, *, stale_before: datetime, error_code: str
    ) -> list[UUID]:
        try:
            async with self._session_factory.begin() as session:
                rows = list(
                    await session.scalars(
                        select(ChatRunRow)
                        .where(
                            ChatRunRow.status.in_(ACTIVE_RUN_STATUSES),
                            or_(
                                ChatRunRow.heartbeat_at < stale_before,
                                and_(
                                    ChatRunRow.heartbeat_at.is_(None),
                                    ChatRunRow.created_at < stale_before,
                                ),
                            ),
                        )
                        .with_for_update()
                    )
                )
                run_ids: list[UUID] = []
                completed_at = datetime.now(UTC)
                for row in rows:
                    row.status = "interrupted"
                    row.error_code = error_code
                    row.completed_at = completed_at
                    run_ids.append(row.id)
                return run_ids
        except SQLAlchemyError as exc:
            raise ChatRunRepositoryError() from exc

    async def complete_with_turn(
        self,
        *,
        run_id: UUID,
        worker_id: str,
        fencing_token: int,
        public_response: dict,
        assistant_message: str,
        compact_turn: Turn,
        expected_next_turn_index: int | None = None,
    ) -> ChatRunSummary:
        """Commit the final Turn and Run terminal state in one transaction."""

        try:
            async with self._session_factory.begin() as session:
                run = await session.scalar(
                    select(ChatRunRow).where(ChatRunRow.id == run_id).with_for_update()
                )
                if run is None:
                    raise ChatRunNotFoundError()
                if run.worker_id != worker_id or run.fencing_token != fencing_token:
                    raise ChatRunFencingLostError()
                if run.status == "completed":
                    return _summary(run)
                if run.status == "cancel_requested":
                    raise ChatRunStateError("cancel_requested")
                if run.status != "running":
                    raise ChatRunTerminalError()

                session_row = await session.scalar(
                    select(ChatSessionRow)
                    .where(ChatSessionRow.id == run.session_id)
                    .with_for_update()
                )
                if session_row is None:
                    raise ChatRunNotFoundError()
                if session_row.active_fencing_token != fencing_token:
                    raise ChatRunFencingLostError()

                turn_index = session_row.next_turn_index
                if (
                    expected_next_turn_index is not None
                    and turn_index != expected_next_turn_index
                ):
                    raise ChatRunStateError("stale_turn_index")
                stored_turn = compact_turn.model_copy(update={"turn_index": turn_index})
                turn_id = uuid4()
                session.add(
                    ChatTurnRow(
                        id=turn_id,
                        session_id=run.session_id,
                        request_id=run.request_id,
                        payload_hash=run.payload_hash,
                        turn_index=turn_index,
                        user_query=run.user_query,
                        assistant_message=assistant_message,
                        public_response=dict(public_response),
                        compact_turn=stored_turn.model_dump(mode="json"),
                    )
                )
                session_row.next_turn_index += 1
                session_row.updated_at = datetime.now(UTC)
                if not session_row.title_is_custom and turn_index == 1:
                    session_row.title = run.user_query.strip()[:80] or "新对话"

                completed_at = datetime.now(UTC)
                run.status = "completed"
                run.result_turn_id = turn_id
                run.completed_at = completed_at
                run.heartbeat_at = completed_at
                run.error_code = None
                await session.flush()
                return _summary(run)
        except (
            ChatRunFencingLostError,
            ChatRunNotFoundError,
            ChatRunRepositoryError,
            ChatRunStateError,
            ChatRunTerminalError,
        ):
            raise
        except SQLAlchemyError as exc:
            raise ChatRunRepositoryError() from exc

    async def _mark_terminal(
        self,
        *,
        run_id: UUID,
        status: ChatRunStatus,
        error_code: str | None,
        worker_id: str | None,
        allowed_statuses: Iterable[ChatRunStatus],
    ) -> ChatRunSummary:
        try:
            async with self._session_factory.begin() as session:
                row = await session.scalar(
                    select(ChatRunRow).where(ChatRunRow.id == run_id).with_for_update()
                )
                if row is None:
                    raise ChatRunNotFoundError()
                if worker_id is not None and row.worker_id != worker_id:
                    raise ChatRunStateError("run_owned_by_other_worker")
                if row.status not in allowed_statuses:
                    if row.status == status:
                        return _summary(row)
                    raise ChatRunTerminalError()
                row.status = status
                row.error_code = error_code
                row.completed_at = datetime.now(UTC)
                row.heartbeat_at = row.completed_at
                return _summary(row)
        except (
            ChatRunNotFoundError,
            ChatRunRepositoryError,
            ChatRunStateError,
            ChatRunTerminalError,
        ):
            raise
        except SQLAlchemyError as exc:
            raise ChatRunRepositoryError() from exc

    async def _owned_run(
        self,
        session: AsyncSession,
        browser_id: str,
        run_id: UUID,
        *,
        lock: bool = False,
    ) -> ChatRunRow:
        statement = (
            select(ChatRunRow)
            .join(ChatSessionRow, ChatSessionRow.id == ChatRunRow.session_id)
            .where(
                ChatRunRow.id == run_id,
                ChatSessionRow.browser_id_hash == browser_id_hash(browser_id),
            )
        )
        if lock:
            statement = statement.with_for_update()
        row = await session.scalar(statement)
        if row is None:
            raise ChatRunNotFoundError()
        return row
