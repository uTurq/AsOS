"""add calendar_event source and rename canvas_event_id to external_event_id

Revision ID: d2786f3d22d2
Revises: 4bc3a906e93f
Create Date: 2026-09-03 16:34:05.143699

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd2786f3d22d2'
down_revision: Union[str, Sequence[str], None] = '4bc3a906e93f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema.

    Adjusted from the raw autogenerate output in two ways:
      1. Wrapped in batch_alter_table -- SQLite doesn't support ALTER
         for adding a unique constraint or dropping a column directly;
         Alembic's batch mode handles this via a copy-and-move
         strategy under the hood.
      2. Backfills external_event_id from the old canvas_event_id
         column instead of just dropping the data, and gives `source`
         a server_default of 'canvas' so this works even against a
         database that already has rows (every row that could exist
         before this migration can only have come from Canvas sync,
         since that was the only writer at the time).
    """
    with op.batch_alter_table('calendar_events', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                'source',
                sa.Enum('CANVAS', 'ICS_FEED', 'MANUAL', name='calendareventsource', native_enum=False),
                nullable=False,
                server_default='canvas',
            )
        )
        batch_op.add_column(
            sa.Column(
                'external_event_id',
                sa.String(),
                nullable=True,
                comment='Canvas event id, ICS UID, etc. -- unique within its source.',
            )
        )

    op.execute("UPDATE calendar_events SET external_event_id = canvas_event_id")

    with op.batch_alter_table('calendar_events', schema=None) as batch_op:
        batch_op.create_unique_constraint('uq_calendar_events_external_event_id', ['external_event_id'])
        batch_op.drop_column('canvas_event_id')


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('calendar_events', schema=None) as batch_op:
        batch_op.add_column(sa.Column('canvas_event_id', sa.VARCHAR(), nullable=True))

    op.execute("UPDATE calendar_events SET canvas_event_id = external_event_id WHERE source = 'canvas'")

    with op.batch_alter_table('calendar_events', schema=None) as batch_op:
        batch_op.drop_constraint('uq_calendar_events_external_event_id', type_='unique')
        batch_op.drop_column('external_event_id')
        batch_op.drop_column('source')
