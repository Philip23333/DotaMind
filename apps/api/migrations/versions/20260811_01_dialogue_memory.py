"""replace Session discourse state with persisted assistant messages"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20260811_01"
down_revision: Union[str, None] = "20260810_01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_EMPTY_STATE = (
    '{"activations":[],"groups":[],"last_extraction_status":"empty",'
    '"links":[],"next_group_seq":1,"next_referent_seq":1,"referents":[],'
    '"revision":0,"schema_version":1}'
)


def upgrade() -> None:
    op.add_column("chat_turns", sa.Column("assistant_message", sa.Text(), nullable=True))
    op.execute(
        sa.text(
            """
            UPDATE chat_turns
            SET assistant_message = COALESCE(
                public_response #>> '{answer,summary}',
                public_response ->> 'reason',
                compact_turn ->> 'response_summary',
                ''
            )
            WHERE assistant_message IS NULL
            """
        )
    )
    op.alter_column("chat_turns", "assistant_message", nullable=False)
    op.drop_column("chat_sessions", "discourse_state")


def downgrade() -> None:
    op.add_column(
        "chat_sessions",
        sa.Column(
            "discourse_state",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text(f"'{_EMPTY_STATE}'::jsonb"),
        ),
    )
    op.alter_column("chat_sessions", "discourse_state", server_default=None)
    op.drop_column("chat_turns", "assistant_message")
