"""Add People display metadata after the OrgMesh Word head.

This additive revision follows the current Word head without changing ancestry.
"""

from alembic import op
import sqlalchemy as sa

revision = "d83f0b6c1e92"
down_revision = "c71e9a2d4f60"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "orgmesh_person",
        sa.Column("employee_id", sa.String(), primary_key=True),
        sa.Column("email", sa.String(), nullable=False, unique=True),
        sa.Column("work_email", sa.String(), nullable=True),
        sa.Column("display_name", sa.String(), nullable=True),
        sa.Column("job_title", sa.String(), nullable=True),
        sa.Column("avatar_url", sa.Text(), nullable=True),
        sa.Column("manager_id", sa.String(), nullable=True),
    )
    op.create_index("ix_orgmesh_person_manager_id", "orgmesh_person", ["manager_id"])
    op.create_table(
        "orgmesh_department",
        sa.Column("department_id", sa.String(), primary_key=True),
        sa.Column("name", sa.String(), nullable=True),
        sa.Column("parent_id", sa.String(), nullable=True),
    )
    op.create_table(
        "orgmesh_person_department",
        sa.Column(
            "employee_id",
            sa.String(),
            sa.ForeignKey("orgmesh_person.employee_id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "department_id",
            sa.String(),
            sa.ForeignKey("orgmesh_department.department_id", ondelete="CASCADE"),
            primary_key=True,
        ),
    )


def downgrade() -> None:
    op.drop_table("orgmesh_person_department")
    op.drop_table("orgmesh_department")
    op.drop_index("ix_orgmesh_person_manager_id", table_name="orgmesh_person")
    op.drop_table("orgmesh_person")
