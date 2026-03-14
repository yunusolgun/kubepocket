"""Add trial_info table

Revision ID: 003
Revises: 002
Create Date: 2026-03-08
"""
from alembic import op
import sqlalchemy as sa

revision      = '003'
down_revision = '002'
branch_labels = None
depends_on    = None


def upgrade():
    op.create_table(
        'trial_info',
        sa.Column('id',               sa.Integer(),  primary_key=True),
        sa.Column('started_at',       sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('notified_expiry',  sa.Boolean(),  server_default='false'),
    )


def downgrade():
    op.drop_table('trial_info')
