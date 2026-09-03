"""rename sync_change_log.canvas_id to external_id

Revision ID: e744ec1aca5d
Revises: d2786f3d22d2
Create Date: 2026-09-03 16:36:52.671316

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e744ec1aca5d'
down_revision: Union[str, Sequence[str], None] = 'd2786f3d22d2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema.

    Adjusted from the raw autogenerate: a true column rename (via
    SQLite batch mode) instead of add-then-drop, so existing data is
    preserved rather than silently discarded.
    """
    with op.batch_alter_table('sync_change_log', schema=None) as batch_op:
        batch_op.alter_column(
            'canvas_id',
            new_column_name='external_id',
            existing_type=sa.String(),
            existing_nullable=True,
            comment='External id from whichever source produced this change (Canvas id, ICS UID, etc.).',
        )


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('sync_change_log', schema=None) as batch_op:
        batch_op.alter_column(
            'external_id',
            new_column_name='canvas_id',
            existing_type=sa.String(),
            existing_nullable=True,
        )
