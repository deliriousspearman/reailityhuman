"""Downloads: files a machine's extras made for people to download (e.g. a VPN client's config).

Revision ID: 0013
Revises: 0012
"""

import sqlalchemy as sa
from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("machines", sa.Column("downloads", sa.JSON))


def downgrade() -> None:
    op.drop_column("machines", "downloads")
