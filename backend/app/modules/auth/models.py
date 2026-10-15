"""Authentication and session tracking SQLAlchemy models."""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.base import Base, UUIDPrimaryKeyMixin, utc_now


class RefreshTokenSession(Base, UUIDPrimaryKeyMixin):
    """Tracks active refresh tokens, rotation history, and session family revocation."""

    __tablename__ = "refresh_token_sessions"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    token_hash: Mapped[str] = mapped_column(
        String(64),
        unique=True,
        nullable=False,
        index=True,
    )
    session_family_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        index=True,
    )
    is_revoked: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )
    replaced_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("refresh_token_sessions.id"),
        nullable=True,
        default=None,
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
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
        Index("idx_refresh_token_sessions_hash", "token_hash"),
        Index("idx_refresh_token_sessions_family", "session_family_id"),
        Index(
            "idx_refresh_token_sessions_replaced",
            "replaced_by_id",
            postgresql_where=text("replaced_by_id IS NOT NULL"),
        ),
    )


class RefreshOperation(Base):
    """Tracks client-initiated idempotent token refresh operations and lost-response recovery."""

    __tablename__ = "refresh_operations"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,  # Client-generated X-Refresh-Operation-Id
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    session_family_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        index=True,
    )
    input_session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("refresh_token_sessions.id", ondelete="RESTRICT"),
        nullable=False,
        unique=True,  # An input session can be rotated exactly once
    )
    output_session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("refresh_token_sessions.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    encrypted_token: Mapped[str] = mapped_column(
        String(512),
        nullable=False,
    )
    recovery_window_expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
    )

    __table_args__ = (
        UniqueConstraint("input_session_id", name="uq_refresh_operations_input"),
        Index("idx_refresh_operations_output", "output_session_id"),
        Index("idx_refresh_operations_family", "session_family_id"),
        Index("idx_refresh_operations_recovery_expiry", "recovery_window_expires_at"),
    )
