"""Pro Labs: an instance's flags, a random value per flag planted into its machines (new each deploy
or reset).

Revision ID: 0009
Revises: 0008
"""

import sqlalchemy as sa
from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "instance_flags",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("instance_id", sa.String(16), nullable=False),
        sa.Column("flag_id", sa.String(32), nullable=False),
        sa.Column("value", sa.String(64), nullable=False),
        sa.Column("planted_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_instance_flags_instance_id", "instance_flags", ["instance_id"])


def downgrade() -> None:
    op.drop_index("ix_instance_flags_instance_id", "instance_flags")
    op.drop_table("instance_flags")
