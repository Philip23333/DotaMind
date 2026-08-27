"""PostgreSQL-backed anonymous browser chat persistence."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import and_, delete, desc, or_, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agentic.conversation.models import ConversationMessage, DialogueTurn, Turn
from app.application.chat_repository import (
    ChatActiveRunSummary,
    ChatCommitResult,
    ChatConversationContext,
    ChatDialogueTurnResult,
    ChatFencingLostError,
    ChatIdempotencyConflictError,
    ChatNotFoundError,
    ChatRepositoryError,
    ChatRequestLookup,
    ChatSessionSnapshot,
    ChatSessionSummary,
    ChatTranscriptTurn,
)
from app.application.chat_run_repository import ACTIVE_RUN_STATUSES
from app.persistence.models import ChatRunRow, ChatSessionRow, ChatTurnRow


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
                result = await session.execute(
                    select(ChatSessionRow, ChatRunRow)
                    .outerjoin(
                        ChatRunRow,
                        and_(
                            ChatRunRow.session_id == ChatSessionRow.id,
                            ChatRunRow.status.in_(ACTIVE_RUN_STATUSES),
                        ),
                    )
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
        return [_summary(session_row, active_row) for session_row, active_row in rows]

    async def get_session(self, browser_id: str, session_id: UUID) -> ChatSessionSnapshot:
        try:
            async with self._session_factory() as session:
                result = await session.execute(
                    select(ChatSessionRow, ChatRunRow)
                    .outerjoin(
                        ChatRunRow,
                        and_(
                            ChatRunRow.session_id == ChatSessionRow.id,
                            ChatRunRow.status.in_(ACTIVE_RUN_STATUSES),
                        ),
                    )
                    .where(
                        ChatSessionRow.id == session_id,
                        ChatSessionRow.browser_id_hash == browser_id_hash(browser_id),
                    )
                )
                row = result.first()
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
            summary=_summary(row[0], row[1]),
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

    async def get_all_dialogue_turns(
        self,
        browser_id: str,
        session_id: UUID,
    ) -> tuple[list[DialogueTurn], int]:
        """Load the authoritative full dialogue for rebuilding the Redis window."""

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
                result = await session.scalars(
                    select(ChatTurnRow)
                    .where(ChatTurnRow.session_id == session_id)
                    .order_by(ChatTurnRow.turn_index)
                )
                turns = [
                    DialogueTurn(
                        turn_index=item.turn_index,
                        user_message=item.user_query,
                        assistant_message=item.assistant_message,
                    )
                    for item in result.all()
                ]
        except ChatNotFoundError:
            raise
        except SQLAlchemyError as exc:
            raise ChatRepositoryError() from exc
        return turns, row.next_turn_index

    async def get_next_turn_index(self, browser_id: str, session_id: UUID) -> int:
        """Read the durable session counter without loading message bodies."""

        try:
            async with self._session_factory() as session:
                row = await session.scalar(
                    select(ChatSessionRow.next_turn_index).where(
                        ChatSessionRow.id == session_id,
                        ChatSessionRow.browser_id_hash == browser_id_hash(browser_id),
                    )
                )
                if row is None:
                    raise ChatNotFoundError()
        except ChatNotFoundError:
            raise
        except SQLAlchemyError as exc:
            raise ChatRepositoryError() from exc
        return int(row)

    async def lookup_dialogue(
        self,
        browser_id: str,
        session_id: UUID,
        *,
        query_text: str | None = None,
        turn_indexes: list[int] | None = None,
        before_turn_index: int | None = None,
        limit: int = 8,
    ) -> list[DialogueTurn]:
        """Load selected older turns for the request-local history lookup."""

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
                statement = select(ChatTurnRow).where(ChatTurnRow.session_id == session_id)
                if turn_indexes:
                    statement = statement.where(ChatTurnRow.turn_index.in_(turn_indexes))
                if before_turn_index is not None:
                    statement = statement.where(ChatTurnRow.turn_index < before_turn_index)
                if query_text:
                    pattern = f"%{query_text}%"
                    statement = statement.where(
                        or_(
                            ChatTurnRow.user_query.ilike(pattern),
                            ChatTurnRow.assistant_message.ilike(pattern),
                        )
                    )
                statement = statement.order_by(ChatTurnRow.turn_index.desc()).limit(limit)
                result = await session.scalars(statement)
                rows = list(result.all())
        except ChatNotFoundError:
            raise
        except SQLAlchemyError as exc:
            raise ChatRepositoryError() from exc
        return [
            DialogueTurn(
                turn_index=item.turn_index,
                user_message=item.user_query,
                assistant_message=item.assistant_message,
            )
            for item in reversed(rows)
        ]

    async def get_conversation_context(
        self,
        browser_id: str,
        session_id: UUID,
        limit: int,
    ) -> ChatConversationContext:
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
        return ChatConversationContext(
            recent_messages=[
                message
                for item in reversed(rows)
                for message in (
                    ConversationMessage(
                        turn_index=item.turn_index,
                        role="user",
                        content=item.user_query,
                    ),
                    ConversationMessage(
                        turn_index=item.turn_index,
                        role="assistant",
                        content=item.assistant_message,
                    ),
                )
            ],
            next_turn_index=row.next_turn_index,
        )

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

    async def lookup_dialogue_request(
        self,
        browser_id: str,
        session_id: UUID,
        request_id: UUID,
        user_query: str,
    ) -> ChatDialogueTurnResult | None:
        """Find a product-chat retry without exposing Legacy response shapes."""

        payload_hash = _dialogue_payload_hash(user_query)
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
            return None
        if row.payload_hash != payload_hash:
            raise ChatIdempotencyConflictError()
        return ChatDialogueTurnResult(
            status="replay",
            turn_index=row.turn_index,
            assistant_message=row.assistant_message,
        )

    async def append_dialogue_turn(
        self,
        *,
        browser_id: str,
        session_id: UUID,
        request_id: UUID,
        user_query: str,
        assistant_message: str,
    ) -> ChatDialogueTurnResult:
        """Persist one User/Final Assistant dialogue pair for product chat.

        ``public_response`` and ``compact_turn`` are Legacy table columns.  Their
        smallest compatible values remain contained here, outside the vNext
        runtime and product service.
        """

        payload_hash = _dialogue_payload_hash(user_query)
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
                existing = await session.scalar(
                    select(ChatTurnRow).where(
                        ChatTurnRow.session_id == session_id,
                        ChatTurnRow.request_id == request_id,
                    )
                )
                if existing is not None:
                    if existing.payload_hash != payload_hash:
                        raise ChatIdempotencyConflictError()
                    return ChatDialogueTurnResult(
                        status="replay",
                        turn_index=existing.turn_index,
                        assistant_message=existing.assistant_message,
                    )

                turn_index = row.next_turn_index
                row.next_turn_index += 1
                row.updated_at = datetime.now(UTC)
                if not row.title_is_custom and turn_index == 1:
                    row.title = user_query.strip()[:80] or "新对话"
                compatibility_response = {
                    "status": "ok",
                    "answer": {"summary": assistant_message},
                }
                compact_turn = Turn(
                    query=user_query,
                    response_summary=assistant_message,
                    turn_index=turn_index,
                )
                session.add(
                    ChatTurnRow(
                        session_id=session_id,
                        request_id=request_id,
                        payload_hash=payload_hash,
                        turn_index=turn_index,
                        user_query=user_query,
                        assistant_message=assistant_message,
                        public_response=compatibility_response,
                        compact_turn=compact_turn.model_dump(mode="json"),
                    )
                )
        except (ChatNotFoundError, ChatIdempotencyConflictError):
            raise
        except SQLAlchemyError as exc:
            raise ChatRepositoryError() from exc
        return ChatDialogueTurnResult(
            status="executed",
            turn_index=turn_index,
            assistant_message=assistant_message,
        )

    async def commit_turn(
        self,
        *,
        browser_id: str,
        session_id: UUID,
        request_id: UUID,
        payload_hash: str,
        fencing_token: int,
        user_query: str,
        assistant_message: str,
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
                        assistant_message=assistant_message,
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


def _summary(
    row: ChatSessionRow,
    active_run: ChatRunRow | None = None,
) -> ChatSessionSummary:
    return ChatSessionSummary(
        session_id=row.id,
        game=row.game,
        title=row.title,
        title_is_custom=row.title_is_custom,
        is_pinned=row.is_pinned,
        created_at=row.created_at,
        updated_at=row.updated_at,
        active_run=(
            ChatActiveRunSummary(
                run_id=active_run.id,
                status=active_run.status,  # type: ignore[arg-type]
                last_event_sequence=active_run.last_event_sequence,
                error_code=active_run.error_code,
            )
            if active_run is not None
            else None
        ),
    )


def _dialogue_payload_hash(user_query: str) -> str:
    return hashlib.sha256(user_query.encode("utf-8")).hexdigest()


def _transcript_turn(row: ChatTurnRow) -> ChatTranscriptTurn:
    return ChatTranscriptTurn(
        turn_index=row.turn_index,
        request_id=row.request_id,
        user_query=row.user_query,
        public_response=dict(row.public_response),
        created_at=row.created_at,
    )
