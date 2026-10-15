"""Immutable audit log SQLAlchemy models."""

import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, String, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.base import Base, UUIDPrimaryKeyMixin, utc_now


class AuditTargetType(str, enum.Enum):
    ORGANIZATION = "ORGANIZATION"
    PROJECT = "PROJECT"
    MEMBER = "MEMBER"
    BOARD = "BOARD"
    SECURITY = "SECURITY"


class AuditLog(Base, UUIDPrimaryKeyMixin):
    """Append-only immutable record of governance and administrative security events."""

    __tablename__ = "audit_logs"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id"),
        nullable=False,
        index=True,
    )
    actor_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=True,
        default=None,
    )
    action: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )
    target_type: Mapped[AuditTargetType] = mapped_column(
        String(50),
        nullable=False,
    )
    target_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
        default=None,
    )
    payload: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB,
        nullable=True,
        default=None,
    )
    ip_address: Mapped[str | None] = mapped_column(
        String(45),
        nullable=True,
        default=None,
    )
    user_agent: Mapped[str | None] = mapped_column(
        String(512),
        nullable=True,
        default=None,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
    )

    __table_args__ = (
        Index("idx_audit_logs_org_created", "organization_id", text("created_at DESC")),
    )
