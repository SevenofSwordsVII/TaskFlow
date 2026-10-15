"""Integration tests for event-driven notification dispatch and read-state management."""

import uuid
from unittest.mock import AsyncMock, MagicMock

from app.core.base import utc_now
from app.core.exceptions import NotFoundException
from app.modules.notifications.models import Notification, NotificationType
from app.modules.notifications.service import NotificationService
from tests.utils import run_async


def test_mark_notification_as_read_scoped_to_user() -> None:
    """Marking notification as read must be scoped strictly to the notification owner."""
    user_id = uuid.uuid4()
    notification_id = uuid.uuid4()

    notification = MagicMock(spec=Notification)
    notification.id = notification_id
    notification.user_id = user_id
    notification.organization_id = uuid.uuid4()
    notification.actor_id = None
    notification.is_read = False
    notification.event_type = NotificationType.TASK_ASSIGNED
    notification.title = "New Task"
    notification.message = "You were assigned"
    notification.link_url = None
    notification.data = None
    notification.created_at = utc_now()

    db = AsyncMock()
    db.execute.return_value = MagicMock(one_or_none=MagicMock(return_value=(notification, None)))

    service = NotificationService(db)
    read_res = run_async(service.mark_as_read(notification_id=notification_id, user_id=user_id))
    assert read_res.is_read is True
    assert notification.is_read is True
    assert db.commit.called


def test_mark_other_user_notification_raises_404() -> None:
    """Attempting to mark another user's notification as read returns 404 NOT_FOUND."""
    db = AsyncMock()
    db.execute.return_value = MagicMock(one_or_none=MagicMock(return_value=None))

    service = NotificationService(db)
    try:
        run_async(service.mark_as_read(notification_id=uuid.uuid4(), user_id=uuid.uuid4()))
        assert False, "Expected NotFoundException"
    except NotFoundException as exc:
        assert exc.code == "NOTIFICATION_NOT_FOUND"


def test_mark_all_read_executes_batch_update() -> None:
    """Mark all read executes single batch update for user."""
    db = AsyncMock()
    user_id = uuid.uuid4()

    service = NotificationService(db)
    run_async(service.mark_all_read(user_id=user_id))

    assert db.execute.called
    assert db.commit.called


if __name__ == "__main__":
    test_mark_notification_as_read_scoped_to_user()
    test_mark_other_user_notification_raises_404()
    test_mark_all_read_executes_batch_update()
    print("All notifications integration tests passed successfully!")
