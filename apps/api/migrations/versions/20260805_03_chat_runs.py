"""add durable chat run lifecycle records"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20260805_03"
down_revision: Union[str, None] = "20260805_02"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "chat_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("request_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("payload_hash", sa.String(length=64), nullable=False),
        sa.Column("user_query", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("fencing_token", sa.BigInteger(), nullable=True),
        sa.Column("worker_id", sa.String(length=128), nullable=True),
        sa.Column("last_event_sequence", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("result_turn_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancel_requested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'cancel_requested', 'completed', "
            "'failed', 'cancelled', 'interrupted')",
            name="ck_chat_runs_status",
        ),
        sa.ForeignKeyConstraint(
            ["session_id"], ["chat_sessions.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["result_turn_id"], ["chat_turns.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("session_id", "request_id", name="uq_chat_runs_session_request"),
    )
    op.alter_column("chat_runs", "last_event_sequence", server_default=None)

    op.create_index(
        "ix_chat_runs_session_status",
        "chat_runs",
        ["session_id", "status"],
    )
    op.create_index(
        "ix_chat_runs_status_heartbeat",
        "chat_runs",
        ["status", "heartbeat_at"],
    )
    op.create_index(
        "ix_chat_runs_worker_status",
        "chat_runs",
        ["worker_id", "status"],
    )
    op.create_index(
        "uq_chat_runs_active_session",
        "chat_runs",
        ["session_id"],
        unique=True,
        postgresql_where=sa.text(
            "status IN ('queued', 'running', 'cancel_requested')"
        ),
    )
    op.create_index(
        "uq_chat_runs_result_turn",
        "chat_runs",
        ["result_turn_id"],
        unique=True,
        postgresql_where=sa.text("result_turn_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_chat_runs_result_turn", table_name="chat_runs")
    op.drop_index("uq_chat_runs_active_session", table_name="chat_runs")
    op.drop_index("ix_chat_runs_worker_status", table_name="chat_runs")
    op.drop_index("ix_chat_runs_status_heartbeat", table_name="chat_runs")
    op.drop_index("ix_chat_runs_session_status", table_name="chat_runs")
    op.drop_table("chat_runs")
