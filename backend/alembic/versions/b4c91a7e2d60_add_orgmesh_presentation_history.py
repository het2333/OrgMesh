"""Add owner-scoped presentation history.

Revision ID: b4c91a7e2d60
Revises: 8266b8886041
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "b4c91a7e2d60"
down_revision = "8266b8886041"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "orgmesh_presentation_task",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("user.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("engine_task_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("presentation_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "project_id",
            sa.Integer(),
            sa.ForeignKey("user_project.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "source_chat_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("chat_session.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column(
            "is_imported", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "user_id",
            "engine_task_id",
            name="uq_orgmesh_presentation_task_owner_engine",
        ),
        sa.CheckConstraint(
            "status IN ('submitting', 'pending', 'completed', 'error')",
            name="ck_orgmesh_presentation_task_status",
        ),
    )
    op.create_index(
        "ix_orgmesh_presentation_task_owner_created",
        "orgmesh_presentation_task",
        ["user_id", "created_at", "id"],
    )
    op.create_table(
        "orgmesh_presentation_record",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("user.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "engine_presentation_id", postgresql.UUID(as_uuid=True), nullable=False
        ),
        sa.Column(
            "task_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("orgmesh_presentation_task.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "user_id",
            "engine_presentation_id",
            name="uq_orgmesh_presentation_record_owner_engine",
        ),
    )
    op.create_index(
        "ix_orgmesh_presentation_record_owner_created",
        "orgmesh_presentation_record",
        ["user_id", "created_at", "id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_orgmesh_presentation_record_owner_created",
        table_name="orgmesh_presentation_record",
    )
    op.drop_table("orgmesh_presentation_record")
    op.drop_index(
        "ix_orgmesh_presentation_task_owner_created",
        table_name="orgmesh_presentation_task",
    )
    op.drop_table("orgmesh_presentation_task")
