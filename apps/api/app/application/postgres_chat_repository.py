"""PostgreSQL-backed anonymous browser chat persistence."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import delete, desc, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agentic.conversation.models import Turn
from app.application.chat_repository import (
    ChatCommitResult,
    ChatFencingLostError,
    ChatIdempotencyConflictError,
    ChatNotFoundError,
    ChatRepositoryError,
    ChatRequestLookup,
    ChatSessionSnapshot,
    ChatSessionSummary,
    ChatTranscriptTurn,
)
from app.persistence.models import ChatSessionRow, ChatTurnRow


def browser_id_hash(browser_id: str) -> str:
    try:
        parsed = UUID(browser_id)
    except (AttributeError, ValueError) as exc:
        raise ChatRepositoryError("invalid_browser_id") from exc
    if parsed.version != 4:
        raise ChatRepositoryError("invalid_browser_id")
    return hashlib.sha256(str(parsed).encode("utf-8")).hexdigest()


class PostgresChatRepository:
    """Repository whose rows are the authoritative chat and Turn history."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def create_session(self, browser_id: str, game: str = "dota2") -> ChatSessionSummary:
        row = ChatSessionRow(browser_id_hash=browser_id_hash(browser_id), game=game)
        try:
            async with self._session_factory.begin() as session:
                session.add(row)
        except SQLAlchemyError as exc:
            raise ChatRepositoryError() from exc
        return _summary(row)

    async def list_sessions(self, browser_id: str) -> list[ChatSessionSummary]:
        try:
            async with self._session_factory() as session:
                result = await session.scalars(
                    select(ChatSessionRow)
                    .where(ChatSessionRow.browser_id_hash == browser_id_hash(browser_id))
                    .order_by(
                        desc(ChatSessionRow.is_pinned),
                        desc(ChatSessionRow.updated_at),
                        desc(ChatSessionRow.id),
                    )
                )
                rows = result.all()
        except SQLAlchemyError as exc:
            raise ChatRepositoryError() from exc
        return [_summary(row) for row in rows]

    async def get_session(self, browser_id: str, session_id: UUID) -> ChatSessionSnapshot:
        try:
            async with self._session_factory() as session:
                row = await session.scalar(
                    select(ChatSessionRow).where(
                        ChatSessionRow.id == session_id,
                        ChatSessionRow.browser_id_hash == browser_id_hash(browser_id),
                    )
                )
                if row is None:
                    raise ChatNotFoundError()
                turns = await session.scalars(
                    select(ChatTurnRow)
                    .where(ChatTurnRow.session_id == session_id)
                    .order_by(ChatTurnRow.turn_index)
                )
                turn_rows = turns.all()
        except ChatNotFoundError:
            raise
        except SQLAlchemyError as exc:
            raise ChatRepositoryError() from exc
        return ChatSessionSnapshot(
            summary=_summary(row),
            turns=[_transcript_turn(turn) for turn in turn_rows],
        )

    async def rename_session(
        self, browser_id: str, session_id: UUID, title: str
    ) -> ChatSessionSummary:
        return await self.update_session(browser_id, session_id, title=title)

    async def update_session(
        self,
        browser_id: str,
        session_id: UUID,
        *,
        title: str | None = None,
        is_pinned: bool | None = None,
    ) -> ChatSessionSummary:
        if title is not None:
            title = title.strip()
            if not title or len(title) > 80:
                raise ChatRepositoryError("invalid_title")
        if title is None and is_pinned is None:
            raise ChatRepositoryError("invalid_update")
        try:
            async with self._session_factory.begin() as session:
                row = await session.scalar(
                    select(ChatSessionRow).where(
                        ChatSessionRow.id == session_id,
                        ChatSessionRow.browser_id_hash == browser_id_hash(browser_id),
                    )
                )
                if row is None:
                    raise ChatNotFoundError()
                if title is not None:
                    row.title = title
                    row.title_is_custom = True
                    row.updated_at = datetime.now(UTC)
                if is_pinned is not None:
                    row.is_pinned = is_pinned
        except (ChatNotFoundError, ChatRepositoryError):
            raise
        except SQLAlchemyError as exc:
            raise ChatRepositoryError() from exc
        return _summary(row)

    async def delete_session(self, browser_id: str, session_id: UUID) -> None:
        try:
            async with self._session_factory.begin() as session:
                result = await session.execute(
                    delete(ChatSessionRow).where(
                        ChatSessionRow.id == session_id,
                        ChatSessionRow.browser_id_hash == browser_id_hash(browser_id),
                    )
                )
                if result.rowcount != 1:
                    raise ChatNotFoundError()
        except (ChatNotFoundError, ChatRepositoryError):
            raise
        except SQLAlchemyError as exc:
            raise ChatRepositoryError() from exc

    async def claim_fencing(
        self,
        browser_id: str,
        session_id: UUID,
        fencing_token: int | None = None,
    ) -> int:
        """Atomically allocate or validate a strictly increasing fencing token.

        New callers omit ``fencing_token`` so PostgreSQL remains the source of
        truth even when Redis loses its session metadata.  The explicit form is
        retained for stale-owner validation and migration compatibility.
        """

        try:
            async with self._session_factory.begin() as session:
                row = await session.scalar(
                    select(ChatSessionRow)
                    .where(
                        ChatSessionRow.id == session_id,
                        ChatSessionRow.browser_id_hash == browser_id_hash(browser_id),
                    )
                    .with_for_update()
                )
                if row is None:
                    raise ChatNotFoundError()
                next_token = row.active_fencing_token + 1
                if fencing_token is not None:
                    if fencing_token <= row.active_fencing_token:
                        raise ChatFencingLostError()
                    next_token = fencing_token
                row.active_fencing_token = next_token
                return next_token
        except (ChatNotFoundError, ChatFencingLostError, ChatRepositoryError):
            raise
        except SQLAlchemyError as exc:
            raise ChatRepositoryError() from exc

    async def allocate_fencing_token(self, browser_id: str, session_id: UUID) -> int:
        """Allocate the next durable fencing token in PostgreSQL."""

        return await self.claim_fencing(browser_id, session_id)

    async def get_history(
        self,
        browser_id: str,
        session_id: UUID,
        limit: int,
    ) -> list[Turn]:
        try:
            async with self._session_factory() as session:
                owner = await session.scalar(
                    select(ChatSessionRow.id).where(
                        ChatSessionRow.id == session_id,
                        ChatSessionRow.browser_id_hash == browser_id_hash(browser_id),
                    )
                )
                if owner is None:
                    raise ChatNotFoundError()
                result = await session.scalars(
                    select(ChatTurnRow)
                    .where(ChatTurnRow.session_id == session_id)
                    .order_by(ChatTurnRow.turn_index.desc())
                    .limit(limit)
                )
                rows = list(result.all())
        except ChatNotFoundError:
            raise
        except SQLAlchemyError as exc:
            raise ChatRepositoryError() from exc
        return [Turn.model_validate(row.compact_turn) for row in reversed(rows)]

    async def lookup_request(
        self,
        browser_id: str,
        session_id: UUID,
        request_id: UUID,
        payload_hash: str,
    ) -> ChatRequestLookup:
        try:
            async with self._session_factory() as session:
                owner = await session.scalar(
                    select(ChatSessionRow.id).where(
                        ChatSessionRow.id == session_id,
                        ChatSessionRow.browser_id_hash == browser_id_hash(browser_id),
                    )
                )
                if owner is None:
                    raise ChatNotFoundError()
                row = await session.scalar(
                    select(ChatTurnRow).where(
                        ChatTurnRow.session_id == session_id,
                        ChatTurnRow.request_id == request_id,
                    )
                )
        except ChatNotFoundError:
            raise
        except SQLAlchemyError as exc:
            raise ChatRepositoryError() from exc
        if row is None:
            return ChatRequestLookup(status="missing")
        if row.payload_hash != payload_hash:
            raise ChatIdempotencyConflictError()
        return ChatRequestLookup(status="replay", public_response=dict(row.public_response))

    async def commit_turn(
        self,
        *,
        browser_id: str,
        session_id: UUID,
        request_id: UUID,
        payload_hash: str,
        fencing_token: int,
        user_query: str,
        public_response: dict[str, Any],
        compact_turn: Turn,
    ) -> ChatCommitResult:
        try:
            async with self._session_factory.begin() as session:
                row = await session.scalar(
                    select(ChatSessionRow)
                    .where(
                        ChatSessionRow.id == session_id,
                        ChatSessionRow.browser_id_hash == browser_id_hash(browser_id),
                    )
                    .with_for_update()
                )
                if row is None:
                    raise ChatNotFoundError()
                if row.active_fencing_token != fencing_token:
                    raise ChatFencingLostError()
                existing = await session.scalar(
                    select(ChatTurnRow).where(
                        ChatTurnRow.session_id == session_id,
                        ChatTurnRow.request_id == request_id,
                    )
                )
                if existing is not None:
                    if existing.payload_hash != payload_hash:
                        raise ChatIdempotencyConflictError()
                    return ChatCommitResult(
                        status="replay",
                        turn_index=existing.turn_index,
                        public_response=dict(existing.public_response),
                        session_summary=_summary(row),
                    )

                turn_index = row.next_turn_index
                row.next_turn_index += 1
                row.updated_at = datetime.now(UTC)
                if not row.title_is_custom and turn_index == 1:
                    row.title = user_query.strip()[:80] or "新对话"
                stored_turn = compact_turn.model_copy(update={"turn_index": turn_index})
                session.add(
                    ChatTurnRow(
                        session_id=session_id,
                        request_id=request_id,
                        payload_hash=payload_hash,
                        turn_index=turn_index,
                        user_query=user_query,
                        public_response=dict(public_response),
                        compact_turn=stored_turn.model_dump(mode="json"),
                    )
                )
        except (ChatNotFoundError, ChatIdempotencyConflictError, ChatFencingLostError):
            raise
        except SQLAlchemyError as exc:
            raise ChatRepositoryError() from exc
        return ChatCommitResult(
            status="executed",
            turn_index=turn_index,
            public_response=dict(public_response),
            session_summary=_summary(row),
        )


def _summary(row: ChatSessionRow) -> ChatSessionSummary:
    return ChatSessionSummary(
        session_id=row.id,
        game=row.game,
        title=row.title,
        title_is_custom=row.title_is_custom,
        is_pinned=row.is_pinned,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _transcript_turn(row: ChatTurnRow) -> ChatTranscriptTurn:
    return ChatTranscriptTurn(
        turn_index=row.turn_index,
        request_id=row.request_id,
        user_query=row.user_query,
        public_response=dict(row.public_response),
        created_at=row.created_at,
    )
