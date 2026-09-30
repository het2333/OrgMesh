"""add orgmesh employee directory

Revision ID: 8266b8886041
Revises: ad99acb9be41
Create Date: 2026-09-30 11:48:07.882546

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "8266b8886041"
down_revision = "ad99acb9be41"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "orgmesh_directory_user",
        sa.Column("email", sa.String(), primary_key=True),
        sa.Column("employee_id", sa.String(), nullable=False),
        sa.Column("department_ids", postgresql.ARRAY(sa.String()), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("orgmesh_directory_user")
