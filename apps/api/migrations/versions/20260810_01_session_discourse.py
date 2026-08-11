"""add authoritative Session discourse state"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20260810_01"
down_revision: Union[str, None] = "20260805_03"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_EMPTY_STATE = (
    '{"activations":[],"groups":[],"last_extraction_status":"empty",'
    '"links":[],"next_group_seq":1,"next_referent_seq":1,"referents":[],'
    '"revision":0,"schema_version":1}'
)
_EMPTY_STATE_SQL = _EMPTY_STATE.replace(":", "\\:")


def upgrade() -> None:
    op.add_column(
        "chat_sessions",
        sa.Column(
            "discourse_state",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text(f"'{_EMPTY_STATE_SQL}'::jsonb"),
        ),
    )
    op.alter_column("chat_sessions", "discourse_state", server_default=None)


def downgrade() -> None:
    op.drop_column("chat_sessions", "discourse_state")
