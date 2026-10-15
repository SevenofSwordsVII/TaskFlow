"""Initial migration: identity, auth sessions, organizations, and memberships.

Revision ID: 001_initial_auth_and_orgs
Revises:
Create Date: 2026-10-11
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "001_initial_auth_and_orgs"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. users table
    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("hashed_password", sa.String(255), nullable=False),
        sa.Column("full_name", sa.String(255), nullable=False),
        sa.Column("avatar_url", sa.String(1024), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("is_superuser", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(now() AT TIME ZONE 'UTC')"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(now() AT TIME ZONE 'UTC')"),
            nullable=False,
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "uq_users_lower_email",
        "users",
        [sa.text("lower(email)")],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )

    # 2. refresh_token_sessions table
    op.create_table(
        "refresh_token_sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("session_family_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("is_revoked", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column(
            "replaced_by_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("refresh_token_sessions.id"),
            nullable=True,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ip_address", sa.String(45), nullable=True),
        sa.Column("user_agent", sa.String(512), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(now() AT TIME ZONE 'UTC')"),
            nullable=False,
        ),
    )
    op.create_index(
        "idx_refresh_token_sessions_hash", "refresh_token_sessions", ["token_hash"], unique=True
    )
    op.create_index(
        "idx_refresh_token_sessions_family", "refresh_token_sessions", ["session_family_id"]
    )
    op.create_index(
        "idx_refresh_token_sessions_replaced",
        "refresh_token_sessions",
        ["replaced_by_id"],
        postgresql_where=sa.text("replaced_by_id IS NOT NULL"),
    )

    # 3. refresh_operations table
    op.create_table(
        "refresh_operations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("session_family_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "input_session_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("refresh_token_sessions.id", ondelete="RESTRICT"),
            nullable=False,
            unique=True,
        ),
        sa.Column(
            "output_session_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("refresh_token_sessions.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("encrypted_token", sa.String(512), nullable=False),
        sa.Column("recovery_window_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(now() AT TIME ZONE 'UTC')"),
            nullable=False,
        ),
    )
    op.create_index("idx_refresh_operations_output", "refresh_operations", ["output_session_id"])
    op.create_index("idx_refresh_operations_family", "refresh_operations", ["session_family_id"])
    op.create_index(
        "idx_refresh_operations_recovery_expiry",
        "refresh_operations",
        ["recovery_window_expires_at"],
    )

    # 4. organizations table
    op.create_table(
        "organizations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("slug", sa.String(100), nullable=False),
        sa.Column("is_archived", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(now() AT TIME ZONE 'UTC')"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(now() AT TIME ZONE 'UTC')"),
            nullable=False,
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "uq_organizations_slug_active",
        "organizations",
        ["slug"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )

    # 5. organization_members table
    op.create_table(
        "organization_members",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "organization_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("role", sa.String(20), server_default="MEMBER", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(now() AT TIME ZONE 'UTC')"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(now() AT TIME ZONE 'UTC')"),
            nullable=False,
        ),
        sa.UniqueConstraint("organization_id", "user_id", name="uq_org_member_user"),
    )
    op.create_index("idx_org_members_user", "organization_members", ["user_id"])


def downgrade() -> None:
    op.drop_table("organization_members")
    op.drop_table("organizations")
    op.drop_table("refresh_operations")
    op.drop_table("refresh_token_sessions")
    op.drop_table("users")
