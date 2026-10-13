"""Extras chosen for each machine.

Revision ID: 0002
Revises: 0001
"""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("machines", sa.Column("extras", sa.JSON, nullable=False, server_default="[]"))


def downgrade() -> None:
    op.drop_column("machines", "extras")
