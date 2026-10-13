"""When each job was queued, kept apart from when it started running.

Revision ID: 0005
Revises: 0004
"""

import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("jobs", sa.Column("queued_at", sa.DateTime(timezone=True)))
    op.execute("UPDATE jobs SET queued_at = started_at")
    op.alter_column("jobs", "queued_at", nullable=False)
    op.alter_column("jobs", "started_at", nullable=True)
    op.create_index("ix_jobs_queued_at", "jobs", ["queued_at"])


def downgrade() -> None:
    op.execute("UPDATE jobs SET started_at = queued_at WHERE started_at IS NULL")
    op.alter_column("jobs", "started_at", nullable=False)
    op.drop_index("ix_jobs_queued_at", "jobs")
    op.drop_column("jobs", "queued_at")
