"""add admin_audit_events

Revision ID: 2ee58624c6d6
Revises: c8e3b1f4a2d5
Create Date: 2026-08-12 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '2ee58624c6d6'
down_revision: Union[str, None] = 'c8e3b1f4a2d5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'admin_audit_events',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('(CURRENT_TIMESTAMP)'),
            nullable=False,
        ),
        sa.Column('admin_id', sa.Integer(), nullable=False),
        sa.Column('action', sa.String(length=32), nullable=False),
        sa.Column('target_user_id', sa.Integer(), nullable=False),
        sa.Column('before_json', sa.JSON(), nullable=False),
        sa.Column('after_json', sa.JSON(), nullable=False),
        sa.Column('reason', sa.Text(), nullable=True),
        sa.Column('request_id', sa.String(length=64), nullable=True),
        sa.Column('idempotency_key', sa.String(length=128), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('admin_audit_events', schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f('ix_admin_audit_events_created_at'), ['created_at']
        )
        batch_op.create_index(
            batch_op.f('ix_admin_audit_events_admin_id'), ['admin_id']
        )
        batch_op.create_index(
            batch_op.f('ix_admin_audit_events_action'), ['action']
        )
        batch_op.create_index(
            batch_op.f('ix_admin_audit_events_target_user_id'), ['target_user_id']
        )
        batch_op.create_index(
            batch_op.f('ix_admin_audit_events_request_id'), ['request_id']
        )
        batch_op.create_index(
            batch_op.f('ix_admin_audit_events_idempotency_key'), ['idempotency_key']
        )


def downgrade() -> None:
    with op.batch_alter_table('admin_audit_events', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_admin_audit_events_idempotency_key'))
        batch_op.drop_index(batch_op.f('ix_admin_audit_events_request_id'))
        batch_op.drop_index(batch_op.f('ix_admin_audit_events_target_user_id'))
        batch_op.drop_index(batch_op.f('ix_admin_audit_events_action'))
        batch_op.drop_index(batch_op.f('ix_admin_audit_events_admin_id'))
        batch_op.drop_index(batch_op.f('ix_admin_audit_events_created_at'))

    op.drop_table('admin_audit_events')
