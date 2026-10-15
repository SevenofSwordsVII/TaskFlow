"""Centralized declarative metadata registry and base models.

All SQLAlchemy models inherit from Base defined here.
Before Alembic evaluates target_metadata, all models must be imported here.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utc_now() -> datetime:
    """Return timezone-aware current UTC datetime."""
    return datetime.now(UTC)


class Base(DeclarativeBase):
    """Base declarative class for all SQLAlchemy entities."""

    pass


class UUIDPrimaryKeyMixin:
    """Mixin providing UUID v4 primary key."""

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )


class TimestampMixin:
    """Mixin providing timezone-aware UTC created_at and updated_at timestamps."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
        nullable=False,
    )


class SoftDeleteMixin:
    """Mixin providing logical soft-deletion timestamp."""

    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        default=None,
        nullable=True,
    )


# Import all module models to register them on Base.metadata for Alembic discovery.
# Use guarded imports so base.py is importable before all model files exist.
try:
    import app.modules.users.models  # noqa: F401
except ImportError:
    pass

try:
    import app.modules.auth.models  # noqa: F401
except ImportError:
    pass

try:
    import app.modules.organizations.models  # noqa: F401
except ImportError:
    pass

try:
    import app.modules.projects.models  # noqa: F401
except ImportError:
    pass

try:
    import app.modules.kanban.models  # noqa: F401
except ImportError:
    pass

try:
    import app.modules.comments.models  # noqa: F401
except ImportError:
    pass

try:
    import app.modules.notifications.models  # noqa: F401
except ImportError:
    pass

try:
    import app.modules.audit_logs.models  # noqa: F401
except ImportError:
    pass
