"""Pro Labs: a machine's lab instance, its role in the lab, and the action it waits to run (its turn in
the lab's boot order).

Revision ID: 0008
Revises: 0007
"""

import sqlalchemy as sa
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("machines", sa.Column("instance_id", sa.String(16)))
    op.add_column("machines", sa.Column("lab", sa.String(32)))
    op.add_column("machines", sa.Column("role", sa.String(16)))
    op.add_column("machines", sa.Column("pending", sa.String(16)))
    op.create_index("ix_machines_instance_id", "machines", ["instance_id"])


def downgrade() -> None:
    op.drop_index("ix_machines_instance_id", "machines")
    op.drop_column("machines", "pending")
    op.drop_column("machines", "role")
    op.drop_column("machines", "lab")
    op.drop_column("machines", "instance_id")
