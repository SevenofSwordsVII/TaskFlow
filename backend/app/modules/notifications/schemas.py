"""Pydantic v2 schemas for Notifications domain."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.modules.users.schemas import UserBrief


class NotificationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: uuid.UUID
    organization_id: uuid.UUID
    actor_id: uuid.UUID | None
    event_type: str
    title: str
    message: str
    link_url: str | None
    is_read: bool
    created_at: datetime
    actor: UserBrief | None = None


class NotificationListResponse(BaseModel):
    items: list[NotificationRead]
    unread_count: int
