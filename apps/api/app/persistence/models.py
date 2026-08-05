"""SQLAlchemy models for anonymous browser-owned chat persistence."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
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
