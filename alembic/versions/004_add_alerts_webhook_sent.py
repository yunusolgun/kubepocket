"""Add webhook_sent column to alerts

Revision ID: 004
Revises: 003
Create Date: 2026-03-14
"""
from alembic import op
import sqlalchemy as sa

revision      = '004'
down_revision = '003'
branch_labels = None
depends_on    = None


def upgrade():
    op.add_column(
        'alerts',
        sa.Column('webhook_sent', sa.Boolean(), server_default='false', nullable=False)
    )


def downgrade():
    op.drop_column('alerts', 'webhook_sent')
