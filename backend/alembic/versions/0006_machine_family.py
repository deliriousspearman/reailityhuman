"""Each machine's OS family (debian, rhel, windows), kept from when it was deployed.

Revision ID: 0006
Revises: 0005
"""

import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("machines", sa.Column("family", sa.String(16), nullable=False, server_default="debian"))
    # Machines deployed before: their template's family, as templates.yaml has it now.
    from app import catalogue

    machines = sa.table("machines", sa.column("template"), sa.column("version"), sa.column("family"))
    for t in catalogue.catalogue().values():
        if t.family != "debian":
            op.execute(
                machines.update()
                .where(machines.c.template == t.template, machines.c.version == t.version)
                .values(family=t.family)
            )


def downgrade() -> None:
    op.drop_column("machines", "family")
