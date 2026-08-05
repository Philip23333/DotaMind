"""create durable anonymous browser chat tables"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "20260805_01"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "chat_sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("browser_id_hash", sa.String(length=64), nullable=False),
        sa.Column("game", sa.String(length=32), nullable=False),
        sa.Column("title", sa.String(length=80), nullable=False),
        sa.Column("title_is_custom", sa.Boolean(), nullable=False),
        sa.Column("next_turn_index", sa.BigInteger(), nullable=False),
        sa.Column("active_fencing_token", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_chat_sessions_browser_updated",
        "chat_sessions",
        ["browser_id_hash", "updated_at"],
    )
    op.create_table(
        "chat_turns",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("request_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("payload_hash", sa.String(length=64), nullable=False),
        sa.Column("turn_index", sa.BigInteger(), nullable=False),
        sa.Column("user_query", sa.Text(), nullable=False),
        sa.Column("public_response", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("compact_turn", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["session_id"], ["chat_sessions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("session_id", "request_id", name="uq_chat_turns_session_request"),
        sa.UniqueConstraint("session_id", "turn_index", name="uq_chat_turns_session_index"),
    )
    op.create_index("ix_chat_turns_session_index", "chat_turns", ["session_id", "turn_index"])


def downgrade() -> None:
    op.drop_index("ix_chat_turns_session_index", table_name="chat_turns")
    op.drop_table("chat_turns")
    op.drop_index("ix_chat_sessions_browser_updated", table_name="chat_sessions")
    op.drop_table("chat_sessions")
