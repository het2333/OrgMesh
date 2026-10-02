"""Add private, owner-scoped Word documents and immutable versions.

Revision ID: c71e9a2d4f60
Revises: b4c91a7e2d60
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "c71e9a2d4f60"
down_revision = "b4c91a7e2d60"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "orgmesh_word_document",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("user.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("current_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("creation_key", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("creation_hash", sa.String(64), nullable=False),
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
            "user_id", "creation_key", name="uq_word_document_owner_creation"
        ),
    )
    op.create_index(
        "ix_word_document_owner_updated",
        "orgmesh_word_document",
        ["user_id", "updated_at", "id"],
    )
    op.create_table(
        "orgmesh_word_document_version",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "document_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("orgmesh_word_document.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "parent_version_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("orgmesh_word_document_version.id"),
            nullable=True,
        ),
        sa.Column("file_id", sa.String(), nullable=False, unique=True),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column(
            "created_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("user.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("operation", sa.String(16), nullable=False),
        sa.Column("idempotency_key", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "document_id",
            "operation",
            "idempotency_key",
            name="uq_word_version_document_request",
        ),
        sa.CheckConstraint(
            "operation IN ('import', 'manual')", name="ck_word_version_operation"
        ),
    )
    op.create_index(
        "ix_orgmesh_word_document_version_document_id",
        "orgmesh_word_document_version",
        ["document_id"],
    )
    op.create_foreign_key(
        "fk_word_document_current_version",
        "orgmesh_word_document",
        "orgmesh_word_document_version",
        ["current_version_id"],
        ["id"],
        deferrable=True,
        initially="DEFERRED",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_word_document_current_version", "orgmesh_word_document", type_="foreignkey"
    )
    op.drop_index(
        "ix_orgmesh_word_document_version_document_id",
        table_name="orgmesh_word_document_version",
    )
    op.drop_table("orgmesh_word_document_version")
    op.drop_index("ix_word_document_owner_updated", table_name="orgmesh_word_document")
    op.drop_table("orgmesh_word_document")
