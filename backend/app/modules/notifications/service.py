"""Notification domain service handling event dispatch and read state."""

import uuid

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundException
from app.modules.notifications.models import Notification, NotificationEventType
from app.modules.notifications.schemas import NotificationListResponse, NotificationRead
from app.modules.users.models import User
from app.modules.users.schemas import UserBrief


class NotificationService:
    """Service managing user notifications and inbox state."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def dispatch_notification(
        self,
        user_id: uuid.UUID,
        organization_id: uuid.UUID,
        event_type: NotificationEventType,
        title: str,
        message: str,
        actor_id: uuid.UUID | None = None,
        link_url: str | None = None,
    ) -> Notification:
        """Create and persist an event notification."""
        notification = Notification(
            id=uuid.uuid4(),
            user_id=user_id,
            organization_id=organization_id,
            actor_id=actor_id,
            event_type=event_type,
            title=title,
            message=message,
            link_url=link_url,
            is_read=False,
        )
        self.db.add(notification)
        await self.db.commit()
        await self.db.refresh(notification)
        return notification

    async def list_user_notifications(
        self,
        user_id: uuid.UUID,
        limit: int = 50,
    ) -> NotificationListResponse:
        """Retrieve user's notifications ordered by newest first, with unread count."""
        # Unread count
        count_stmt = select(func.count(Notification.id)).where(
            Notification.user_id == user_id,
            Notification.is_read.is_(False),
        )
        unread_count = (await self.db.execute(count_stmt)).scalar() or 0

        # Notifications list with optional actor
        stmt = (
            select(Notification, User)
            .outerjoin(User, User.id == Notification.actor_id)
            .where(Notification.user_id == user_id)
            .order_by(Notification.created_at.desc())
            .limit(limit)
        )
        rows = (await self.db.execute(stmt)).all()

        items = [
            NotificationRead(
                id=n.id,
                user_id=n.user_id,
                organization_id=n.organization_id,
                actor_id=n.actor_id,
                event_type=(
                    n.event_type.value if hasattr(n.event_type, "value") else str(n.event_type)
                ),
                title=n.title,
                message=n.message,
                link_url=n.link_url,
                is_read=n.is_read,
                created_at=n.created_at,
                actor=UserBrief.model_validate(u) if u else None,
            )
            for n, u in rows
        ]

        return NotificationListResponse(items=items, unread_count=unread_count)

    async def mark_as_read(
        self,
        notification_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> NotificationRead:
        """Mark single notification as read."""
        stmt = (
            select(Notification, User)
            .outerjoin(User, User.id == Notification.actor_id)
            .where(
                Notification.id == notification_id,
                Notification.user_id == user_id,
            )
        )
        row = (await self.db.execute(stmt)).one_or_none()
        if not row:
            raise NotFoundException(
                code="NOTIFICATION_NOT_FOUND",
                message="Notification not found.",
            )

        notification, actor = row
        notification.is_read = True
        await self.db.commit()
        await self.db.refresh(notification)

        return NotificationRead(
            id=notification.id,
            user_id=notification.user_id,
            organization_id=notification.organization_id,
            actor_id=notification.actor_id,
            event_type=(
                notification.event_type.value
                if hasattr(notification.event_type, "value")
                else str(notification.event_type)
            ),
            title=notification.title,
            message=notification.message,
            link_url=notification.link_url,
            is_read=notification.is_read,
            created_at=notification.created_at,
            actor=UserBrief.model_validate(actor) if actor else None,
        )

    async def mark_all_read(self, user_id: uuid.UUID) -> None:
        """Mark all unread notifications for user as read in single query."""
        stmt = (
            update(Notification)
            .where(
                Notification.user_id == user_id,
                Notification.is_read.is_(False),
            )
            .values(is_read=True)
        )
        await self.db.execute(stmt)
        await self.db.commit()
