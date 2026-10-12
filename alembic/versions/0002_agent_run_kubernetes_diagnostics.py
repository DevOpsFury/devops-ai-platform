"""Store Kubernetes evidence with each agent run.

Revision ID: 0002_k8s_diagnostics
Revises: 0001_initial
"""
from alembic import op
import sqlalchemy as sa

revision = "0002_k8s_diagnostics"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "agent_runs",
        sa.Column("kubernetes_diagnostics", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("agent_runs", "kubernetes_diagnostics")
