"""add payment_audit_events

Revision ID: c8e3b1f4a2d5
Revises: a7c2f9b1d3e4
Create Date: 2026-08-11 09:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c8e3b1f4a2d5'
down_revision: Union[str, None] = 'a7c2f9b1d3e4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'payment_audit_events',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('(CURRENT_TIMESTAMP)'),
            nullable=False,
        ),
        sa.Column('channel', sa.String(length=32), nullable=False),
        sa.Column('event_type', sa.String(length=32), nullable=False),
        sa.Column('result', sa.String(length=16), nullable=False, server_default=''),
        sa.Column('order_no', sa.String(length=64), nullable=True),
        sa.Column('provider_txn_hint', sa.String(length=32), nullable=True),
        sa.Column('user_id', sa.Integer(), nullable=True),
        sa.Column('detail', sa.JSON(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('payment_audit_events', schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f('ix_payment_audit_events_created_at'), ['created_at']
        )
        batch_op.create_index(
            batch_op.f('ix_payment_audit_events_channel'), ['channel']
        )
        batch_op.create_index(
            batch_op.f('ix_payment_audit_events_event_type'), ['event_type']
        )
        batch_op.create_index(
            batch_op.f('ix_payment_audit_events_order_no'), ['order_no']
        )
        batch_op.create_index(
            batch_op.f('ix_payment_audit_events_user_id'), ['user_id']
        )


def downgrade() -> None:
    with op.batch_alter_table('payment_audit_events', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_payment_audit_events_user_id'))
        batch_op.drop_index(batch_op.f('ix_payment_audit_events_order_no'))
        batch_op.drop_index(batch_op.f('ix_payment_audit_events_event_type'))
        batch_op.drop_index(batch_op.f('ix_payment_audit_events_channel'))
        batch_op.drop_index(batch_op.f('ix_payment_audit_events_created_at'))

    op.drop_table('payment_audit_events')
