"""Machine names are unique: two deploys of the same name at once can't both get through.

Revision ID: 0003
Revises: 0002
"""

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_unique_constraint("machines_name_key", "machines", ["name"])


def downgrade() -> None:
    op.drop_constraint("machines_name_key", "machines")
