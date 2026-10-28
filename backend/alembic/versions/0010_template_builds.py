"""Templates on demand: a template version the panel has deleted or built (docs/plan.md, section 11),
and when a machine was last deployed from it.

Revision ID: 0010
Revises: 0009
"""

import sqlalchemy as sa
from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "template_builds",
        sa.Column("template", sa.String(64), primary_key=True),
        sa.Column("version", sa.String(32), primary_key=True),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("vsphere", sa.String(255)),
        sa.Column("built_at", sa.DateTime(timezone=True)),
        sa.Column("last_deployed_at", sa.DateTime(timezone=True)),
        sa.Column("job_id", sa.Integer),
        sa.Column("detail", sa.Text),
    )
    # Build jobs belong to a template version, not a machine.
    op.add_column("jobs", sa.Column("template", sa.String(100)))


def downgrade() -> None:
    op.drop_column("jobs", "template")
    op.drop_table("template_builds")
