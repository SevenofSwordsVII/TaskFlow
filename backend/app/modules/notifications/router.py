"""Notifications API router handling inbox queries and read-status mutations."""

import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_active_user, get_db
from app.modules.notifications.schemas import NotificationListResponse, NotificationRead
from app.modules.notifications.service import NotificationService
from app.modules.users.models import User

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get(
    "",
    response_model=NotificationListResponse,
    summary="List caller notifications and unread count",
)
async def list_notifications(
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> NotificationListResponse:
    """Retrieve notifications for the authenticated user."""
    service = NotificationService(db)
    return await service.list_user_notifications(user_id=current_user.id)


@router.patch(
    "/{notification_id}/read",
    response_model=NotificationRead,
    summary="Mark notification as read",
)
async def mark_notification_as_read(
    notification_id: uuid.UUID,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> NotificationRead:
    """Mark a specific notification as read."""
    service = NotificationService(db)
    return await service.mark_as_read(notification_id=notification_id, user_id=current_user.id)


@router.post(
    "/mark-all-read",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Mark all notifications as read",
)
async def mark_all_notifications_read(
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Mark all unread notifications for the caller as read."""
    service = NotificationService(db)
    await service.mark_all_read(user_id=current_user.id)
