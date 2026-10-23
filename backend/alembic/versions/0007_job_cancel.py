"""Cancelling a job: who asked, set while it waits or runs; the worker stops it at its next check.

Revision ID: 0007
Revises: 0006
"""

import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("jobs", sa.Column("cancelled_by", sa.String(64)))


def downgrade() -> None:
    op.drop_column("jobs", "cancelled_by")
