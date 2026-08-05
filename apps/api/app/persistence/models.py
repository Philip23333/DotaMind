"""SQLAlchemy models for anonymous browser-owned chat persistence."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utc_now() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class ChatSessionRow(Base):
    __tablename__ = "chat_sessions"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    browser_id_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    game: Mapped[str] = mapped_column(String(32), nullable=False, default="dota2")
    title: Mapped[str] = mapped_column(String(80), nullable=False, default="新对话")
    title_is_custom: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_pinned: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    next_turn_index: Mapped[int] = mapped_column(BigInteger, nullable=False, default=1)
    active_fencing_token: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )

    turns: Mapped[list[ChatTurnRow]] = relationship(
        back_populates="session",
        cascade="all, delete-orphan",
        order_by="ChatTurnRow.turn_index",
    )
    runs: Mapped[list[ChatRunRow]] = relationship(
        back_populates="session",
        cascade="all, delete-orphan",
        order_by="ChatRunRow.created_at",
    )

    __table_args__ = (
        Index("ix_chat_sessions_browser_updated", "browser_id_hash", "updated_at"),
        Index(
            "ix_chat_sessions_browser_pinned_updated",
            "browser_id_hash",
            "is_pinned",
            "updated_at",
        ),
    )


class ChatTurnRow(Base):
    __tablename__ = "chat_turns"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    session_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("chat_sessions.id", ondelete="CASCADE"), nullable=False
    )
    request_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    turn_index: Mapped[int] = mapped_column(BigInteger, nullable=False)
    user_query: Mapped[str] = mapped_column(Text, nullable=False)
    public_response: Mapped[dict] = mapped_column(JSONB, nullable=False)
    compact_turn: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )

    session: Mapped[ChatSessionRow] = relationship(back_populates="turns")

    __table_args__ = (
        UniqueConstraint("session_id", "request_id", name="uq_chat_turns_session_request"),
        UniqueConstraint("session_id", "turn_index", name="uq_chat_turns_session_index"),
        Index("ix_chat_turns_session_index", "session_id", "turn_index"),
    )


class ChatRunRow(Base):
    """Durable lifecycle record for one background chat execution."""

    __tablename__ = "chat_runs"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    session_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("chat_sessions.id", ondelete="CASCADE"), nullable=False
    )
    request_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    user_query: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    fencing_token: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    worker_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    last_event_sequence: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    result_turn_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("chat_turns.id", ondelete="SET NULL"),
        nullable=True,
    )
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    heartbeat_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    cancel_requested_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    session: Mapped[ChatSessionRow] = relationship(back_populates="runs")
    result_turn: Mapped[ChatTurnRow | None] = relationship(
        foreign_keys=[result_turn_id],
        uselist=False,
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('queued', 'running', 'cancel_requested', 'completed', "
            "'failed', 'cancelled', 'interrupted')",
            name="ck_chat_runs_status",
        ),
        UniqueConstraint("session_id", "request_id", name="uq_chat_runs_session_request"),
        Index("ix_chat_runs_session_status", "session_id", "status"),
        Index("ix_chat_runs_status_heartbeat", "status", "heartbeat_at"),
        Index("ix_chat_runs_worker_status", "worker_id", "status"),
        Index(
            "uq_chat_runs_active_session",
            "session_id",
            unique=True,
            postgresql_where=text(
                "status IN ('queued', 'running', 'cancel_requested')"
            ),
        ),
        Index(
            "uq_chat_runs_result_turn",
            "result_turn_id",
            unique=True,
            postgresql_where=text("result_turn_id IS NOT NULL"),
        ),
    )
