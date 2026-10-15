"""Project and project membership domain SQLAlchemy models."""

import enum
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.base import Base, SoftDeleteMixin, TimestampMixin, UUIDPrimaryKeyMixin, utc_now


class ProjectVisibility(str, enum.Enum):
    ORG_PUBLIC = "ORG_PUBLIC"
    RESTRICTED = "RESTRICTED"


class ProjectRole(str, enum.Enum):
    PROJECT_ADMIN = "PROJECT_ADMIN"
    MEMBER = "MEMBER"
    VIEWER = "VIEWER"


class Project(Base, UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin):
    """Project entity representing a distinct workspace initiative."""

    __tablename__ = "projects"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )
    key: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
    )
    description: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        default=None,
    )
    visibility: Mapped[ProjectVisibility] = mapped_column(
        String(20),
        nullable=False,
        default=ProjectVisibility.ORG_PUBLIC,
    )
    is_archived: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )
    created_by_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=False,
    )

    members: Mapped[list["ProjectMember"]] = relationship(
        "ProjectMember",
        back_populates="project",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        Index(
            "uq_projects_org_key_active",
            "organization_id",
            "key",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
    )


class ProjectMember(Base, UUIDPrimaryKeyMixin):
    """Explicit member access grants for RESTRICTED projects."""

    __tablename__ = "project_members"

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    project_role: Mapped[ProjectRole] = mapped_column(
        String(20),
        nullable=False,
        default=ProjectRole.MEMBER,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
    )

    project: Mapped["Project"] = relationship(
        "Project",
        back_populates="members",
    )

    __table_args__ = (UniqueConstraint("project_id", "user_id", name="uq_project_member_user"),)
