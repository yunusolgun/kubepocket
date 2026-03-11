"""
Alembic migration — add trial_info table

Run:
    kubectl exec -n kubepocket deploy/kubepocket -- \
      alembic upgrade head

Or apply manually:
    kubectl exec -n kubepocket kubepocket-postgresql-0 -- \
      env PGPASSWORD=kubepocket123 psql -U kubepocket -d kubepocket -c "
        CREATE TABLE IF NOT EXISTS trial_info (
          id               INTEGER PRIMARY KEY DEFAULT 1,
          started_at       TIMESTAMP NOT NULL DEFAULT NOW(),
          notified_expiry  BOOLEAN DEFAULT FALSE
        );
      "
"""

from alembic import op
import sqlalchemy as sa

revision = 'add_trial_info'
down_revision = None   # set to your latest revision
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'trial_info',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('started_at', sa.DateTime(), nullable=False,
                  server_default=sa.func.now()),
        sa.Column('notified_expiry', sa.Boolean(), server_default='false'),
    )


def downgrade():
    op.drop_table('trial_info')
