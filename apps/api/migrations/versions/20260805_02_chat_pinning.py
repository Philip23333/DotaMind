"""add chat session pinning"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260805_02"
down_revision: str | None = "20260805_01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "chat_sessions",
        sa.Column("is_pinned", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.alter_column("chat_sessions", "is_pinned", server_default=None)
    op.create_index(
        "ix_chat_sessions_browser_pinned_updated",
        "chat_sessions",
        ["browser_id_hash", "is_pinned", "updated_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_chat_sessions_browser_pinned_updated", table_name="chat_sessions")
    op.drop_column("chat_sessions", "is_pinned")
