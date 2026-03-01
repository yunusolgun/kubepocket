"""Add kube_events table

Revision ID: 002
Revises: 001
Create Date: 2026-03-01
"""
from alembic import op
import sqlalchemy as sa

revision = '002'
down_revision = '001'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'kube_events',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('cluster_id', sa.Integer(), nullable=True),
        sa.Column('namespace', sa.String(255), nullable=False),
        sa.Column('pod_name', sa.String(255), nullable=False),
        sa.Column('event_type', sa.String(100), nullable=False),
        sa.Column('reason', sa.String(255), nullable=True),
        sa.Column('message', sa.Text(), nullable=True),
        sa.Column('count', sa.Integer(), default=1),
        sa.Column('first_seen', sa.DateTime(), nullable=True),
        sa.Column('last_seen', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
    )
    op.create_index('ix_kube_events_namespace', 'kube_events', ['namespace'])
    op.create_index('ix_kube_events_pod_name', 'kube_events', ['pod_name'])
    op.create_index('ix_kube_events_event_type', 'kube_events', ['event_type'])
    op.create_index('ix_kube_events_last_seen', 'kube_events', ['last_seen'])
    op.create_index('ix_kube_events_created_at', 'kube_events', ['created_at'])


def downgrade():
    op.drop_table('kube_events')
