"""Project memberships and organization invitations.

Revision ID: 003_projects_and_invitations
Revises: 002_kanban_tables
Create Date: 2026-10-11
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "003_projects_and_invitations"
down_revision: str | None = "002_kanban_tables"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. project_members table
    op.create_table(
        "project_members",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "project_role",
            sa.String(20),
            server_default="MEMBER",
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(now() AT TIME ZONE 'UTC')"),
            nullable=False,
        ),
        sa.UniqueConstraint("project_id", "user_id", name="uq_project_member_user"),
    )
    op.create_index(
        "idx_project_members_project",
        "project_members",
        ["project_id"],
    )
    op.create_index(
        "idx_project_members_user",
        "project_members",
        ["user_id"],
    )

    # 2. organization_invitations table
    op.create_table(
        "organization_invitations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "organization_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column(
            "role",
            sa.String(20),
            server_default="MEMBER",
            nullable=False,
        ),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column(
            "invited_by_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expired_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(now() AT TIME ZONE 'UTC')"),
            nullable=False,
        ),
    )
    op.create_index(
        "idx_org_invitations_org",
        "organization_invitations",
        ["organization_id"],
    )
    op.create_index(
        "idx_org_invitations_hash",
        "organization_invitations",
        ["token_hash"],
    )
    op.execute(
        """
        CREATE UNIQUE INDEX uq_org_invitations_pending
        ON organization_invitations (organization_id, lower(email))
        WHERE accepted_at IS NULL AND revoked_at IS NULL AND expired_at IS NULL;
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_org_invitations_pending;")
    op.drop_table("organization_invitations")
    op.drop_table("project_members")
