"""Kanban domain SQLAlchemy models: Boards, Lists, and Tasks."""

import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.base import Base, SoftDeleteMixin, TimestampMixin, UUIDPrimaryKeyMixin


class TaskPriority(str, enum.Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    URGENT = "URGENT"


class Board(Base, UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin):
    """Kanban board entity containing workflow lists."""

    __tablename__ = "boards"

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
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
    description: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        default=None,
    )
    created_by_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=False,
    )

    lists: Mapped[list["List"]] = relationship(
        "List",
        back_populates="board",
        cascade="all, delete-orphan",
        order_by="List.ordering_key",
    )


class List(Base, UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin):
    """Workflow column inside a Kanban board containing tasks."""

    __tablename__ = "lists"

    board_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("boards.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
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
    ordering_key: Mapped[str] = mapped_column(
        String(255, collation="C"),
        nullable=False,
    )
    version: Mapped[int] = mapped_column(
        Integer,
        default=1,
        nullable=False,
    )

    board: Mapped["Board"] = relationship(
        "Board",
        back_populates="lists",
    )
    tasks: Mapped[list["Task"]] = relationship(
        "Task",
        back_populates="list",
        cascade="all, delete-orphan",
        order_by="Task.ordering_key",
    )

    __table_args__ = (
        Index(
            "idx_lists_board_ordering",
            "board_id",
            "ordering_key",
            postgresql_where=text("deleted_at IS NULL"),
        ),
    )


class Task(Base, UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin):
    """Actionable card unit in a Kanban list with OCC versioning and LexoRank ordering."""

    __tablename__ = "tasks"

    list_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("lists.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    board_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("boards.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    title: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )
    description: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        default=None,
    )
    priority: Mapped[TaskPriority] = mapped_column(
        String(20),
        nullable=False,
        default=TaskPriority.MEDIUM,
    )
    ordering_key: Mapped[str] = mapped_column(
        String(255, collation="C"),
        nullable=False,
    )
    version: Mapped[int] = mapped_column(
        Integer,
        default=1,
        nullable=False,
    )
    assignee_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        default=None,
    )
    due_date: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        default=None,
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        default=None,
    )
    created_by_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=False,
    )

    list: Mapped["List"] = relationship(
        "List",
        back_populates="tasks",
    )
    board: Mapped["Board"] = relationship(
        "Board",
    )

    __table_args__ = (
        Index(
            "idx_tasks_list_ordering",
            "list_id",
            "ordering_key",
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index(
            "idx_tasks_board",
            "board_id",
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index(
            "idx_tasks_assignee",
            "assignee_id",
            postgresql_where=text("deleted_at IS NULL"),
        ),
    )
