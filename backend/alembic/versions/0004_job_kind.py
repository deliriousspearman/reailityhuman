"""Each job's kind (deploy, start, reset...), as well as its label.

Revision ID: 0004
Revises: 0003
"""

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("jobs", sa.Column("kind", sa.String(16), nullable=False, server_default=""))
    # Labels are "<Verb> <machine name>", e.g. "Deploy ubuntu01".
    op.execute("UPDATE jobs SET kind = lower(split_part(action, ' ', 1))")


def downgrade() -> None:
    op.drop_column("jobs", "kind")
