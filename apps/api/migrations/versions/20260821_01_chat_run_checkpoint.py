"""add durable Chat Run Checkpoint state and waiting lifecycle status"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260821_01"
down_revision: str | None = "20260811_01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_STATUS_WITH_CHECKPOINT = (
    "status IN ('queued', 'running', 'waiting_input', 'cancel_requested', "
    "'completed', 'failed', 'cancelled', 'interrupted')"
)
_STATUS_WITHOUT_CHECKPOINT = (
    "status IN ('queued', 'running', 'cancel_requested', 'completed', "
    "'failed', 'cancelled', 'interrupted')"
)


def upgrade() -> None:
    op.add_column(
        "chat_runs",
        sa.Column("checkpoint_state", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.drop_constraint("ck_chat_runs_status", "chat_runs", type_="check")
    op.create_check_constraint(
        "ck_chat_runs_status",
        "chat_runs",
        _STATUS_WITH_CHECKPOINT,
    )
    op.drop_index("uq_chat_runs_active_session", table_name="chat_runs")
    op.create_index(
        "uq_chat_runs_active_session",
        "chat_runs",
        ["session_id"],
        unique=True,
        postgresql_where=sa.text(
            "status IN ('queued', 'running', 'waiting_input', 'cancel_requested')"
        ),
    )


def downgrade() -> None:
    op.drop_index("uq_chat_runs_active_session", table_name="chat_runs")
    op.create_index(
        "uq_chat_runs_active_session",
        "chat_runs",
        ["session_id"],
        unique=True,
        postgresql_where=sa.text(
            "status IN ('queued', 'running', 'cancel_requested')"
        ),
    )
    op.drop_constraint("ck_chat_runs_status", "chat_runs", type_="check")
    op.create_check_constraint(
        "ck_chat_runs_status",
        "chat_runs",
        _STATUS_WITHOUT_CHECKPOINT,
    )
    op.drop_column("chat_runs", "checkpoint_state")
