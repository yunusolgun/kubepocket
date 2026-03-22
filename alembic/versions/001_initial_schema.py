"""Initial schema

Revision ID: 001
Revises: 
Create Date: 2026-02-22

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = '001'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'clusters',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('name', sa.String(255), unique=True, nullable=False),
        sa.Column('context', sa.String(255)),
        sa.Column('created_at', sa.DateTime(), default=sa.func.now()),
        sa.Column('last_seen', sa.DateTime(), default=sa.func.now()),
    )

    op.create_table(
        'metrics',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('cluster_id', sa.Integer(), nullable=False),
        sa.Column('namespace', sa.String(255), nullable=False),
        sa.Column('timestamp', sa.DateTime(), index=True),
        sa.Column('pod_data', sa.JSON()),
        sa.Column('total_cpu', sa.Float(), default=0.0),
        sa.Column('total_memory', sa.Float(), default=0.0),
        sa.Column('total_restarts', sa.Integer(), default=0),
    )

    op.create_table(
        'alerts',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('cluster_id', sa.Integer(), nullable=True),
        sa.Column('namespace', sa.String(255)),
        sa.Column('message', sa.Text()),
        sa.Column('severity', sa.String(50), default='warning'),
        sa.Column('resolved', sa.Boolean(), default=False),
        sa.Column('created_at', sa.DateTime(), default=sa.func.now()),
    )

    op.create_table(
        'statistics',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('cluster_id', sa.Integer(), nullable=True),
        sa.Column('namespace', sa.String(255), nullable=False),
        sa.Column('metric_type', sa.String(50), nullable=False),
        sa.Column('avg_value', sa.Float()),
        sa.Column('std_dev', sa.Float()),
        sa.Column('min_value', sa.Float()),
        sa.Column('max_value', sa.Float()),
        sa.Column('trend_slope', sa.Float(), default=0.0),
        sa.Column('calculated_at', sa.DateTime(), index=True),
    )

    op.create_table(
        'api_keys',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('key_hash', sa.String(64), unique=True, nullable=False),
        sa.Column('is_active', sa.Boolean(), default=True),
        sa.Column('created_at', sa.DateTime(), default=sa.func.now()),
        sa.Column('last_used_at', sa.DateTime(), nullable=True),
        sa.Column('expires_at', sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table('api_keys')
    op.drop_table('statistics')
    op.drop_table('alerts')
    op.drop_table('metrics')
    op.drop_table('clusters')
