"""Organization and membership domain SQLAlchemy models."""

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.base import Base, SoftDeleteMixin, TimestampMixin, UUIDPrimaryKeyMixin, utc_now


class OrganizationRole(str, enum.Enum):
    OWNER = "OWNER"
    ADMIN = "ADMIN"
    MEMBER = "MEMBER"
    VIEWER = "VIEWER"


class Organization(Base, UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin):
    """The root tenant workspace boundary."""

    __tablename__ = "organizations"

    name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )
    slug: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )
    is_archived: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )

    members: Mapped[list["OrganizationMember"]] = relationship(
        "OrganizationMember",
        back_populates="organization",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        Index(
            "uq_organizations_slug_active",
            "slug",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
    )


class OrganizationMember(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Associates users with organizations and assigns workspace-level RBAC roles."""

    __tablename__ = "organization_members"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    role: Mapped[OrganizationRole] = mapped_column(
        String(20),
        nullable=False,
        default=OrganizationRole.MEMBER,
    )

    organization: Mapped["Organization"] = relationship(
        "Organization",
        back_populates="members",
    )

    __table_args__ = (
        UniqueConstraint("organization_id", "user_id", name="uq_org_member_user"),
        Index("idx_org_members_user", "user_id"),
    )


class OrganizationInvitation(Base, UUIDPrimaryKeyMixin):
    """Pending, accepted, revoked, or expired workspace membership invitations."""

    __tablename__ = "organization_invitations"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    email: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )
    role: Mapped[OrganizationRole] = mapped_column(
        String(20),
        nullable=False,
        default=OrganizationRole.MEMBER,
    )
    token_hash: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        unique=True,
    )
    invited_by_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=False,
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    accepted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        default=None,
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        default=None,
    )
    expired_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        default=None,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
    )

    organization: Mapped["Organization"] = relationship(
        "Organization",
    )

    __table_args__ = (
        Index(
            "uq_org_invitations_pending",
            "organization_id",
            text("lower(email)"),
            unique=True,
            postgresql_where=text(
                "accepted_at IS NULL AND revoked_at IS NULL AND expired_at IS NULL"
            ),
        ),
        Index("idx_org_invitations_hash", "token_hash"),
    )
