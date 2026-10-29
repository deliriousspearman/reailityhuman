"""Image CDs: the image ISOs a machine was deployed with (extras.media), attached again after a reset.

Revision ID: 0011
Revises: 0010
"""

import sqlalchemy as sa
from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("machines", sa.Column("media", sa.JSON))


def downgrade() -> None:
    op.drop_column("machines", "media")
