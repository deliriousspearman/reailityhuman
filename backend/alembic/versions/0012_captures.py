"""Packet captures (app/capture.py).

Revision ID: 0012
Revises: 0011
"""

import sqlalchemy as sa
from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "captures",
        sa.Column("id", sa.String(16), primary_key=True),
        sa.Column("owner", sa.String(64), nullable=False),
        sa.Column("machines", sa.JSON, nullable=False),
        sa.Column("user_filter", sa.Text, nullable=False),
        sa.Column("effective_filter", sa.Text, nullable=False),
        sa.Column("seconds", sa.Integer, nullable=False),
        sa.Column("state", sa.String(8), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("stopped_at", sa.DateTime(timezone=True)),
        sa.Column("packets", sa.Integer, nullable=False),
        sa.Column("bytes", sa.BigInteger, nullable=False),
        sa.Column("conversations", sa.JSON, nullable=False),
        sa.Column("detail", sa.Text),
    )


def downgrade() -> None:
    op.drop_table("captures")
