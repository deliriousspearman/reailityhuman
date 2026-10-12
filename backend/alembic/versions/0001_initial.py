"""Machines, their logs, jobs, and the Procrastinate queue's schema.

Revision ID: 0001
Revises:
"""

import sqlalchemy as sa
from alembic import op
from procrastinate.schema import SchemaManager

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "machines",
        sa.Column("id", sa.String(16), primary_key=True),
        sa.Column("name", sa.String(15), nullable=False),
        sa.Column("template", sa.String(64), nullable=False),
        sa.Column("version", sa.String(32), nullable=False),
        sa.Column("owner", sa.String(64), nullable=False),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column("ip", sa.String(64)),
        sa.Column("vm_name", sa.String(80), nullable=False),
        sa.Column("username", sa.String(32), nullable=False),
        sa.Column("password", sa.String(128), nullable=False),
        sa.Column("ssh_key", sa.Text),
    )
    op.create_table(
        "log_lines",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("machine_id", sa.String(16), sa.ForeignKey("machines.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("text", sa.Text, nullable=False),
        sa.Column("tone", sa.String(8)),
    )
    op.create_table(
        "jobs",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("machine_id", sa.String(16), index=True),
        sa.Column("action", sa.String(128), nullable=False),
        sa.Column("by", sa.String(64), nullable=False),
        sa.Column("state", sa.String(8), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("detail", sa.Text),
    )
    # Procrastinate's own tables and functions, as shipped with the pinned version. Run through the
    # raw driver connection: the SQL has % and : characters that SQLAlchemy would read as parameters.
    op.get_bind().connection.driver_connection.execute(SchemaManager.get_schema())


def downgrade() -> None:
    op.drop_table("jobs")
    op.drop_table("log_lines")
    op.drop_table("machines")
