"""Pydantic v2 schemas for Audit Log domain."""

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict

from app.modules.users.schemas import UserBrief


class AuditLogRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organization_id: uuid.UUID
    actor_id: uuid.UUID | None
    action: str
    target_type: str
    target_id: uuid.UUID | None
    payload: dict[str, Any] | None = None
    ip_address: str | None = None
    user_agent: str | None = None
    created_at: datetime
    actor: UserBrief | None = None


class AuditLogListResponse(BaseModel):
    items: list[AuditLogRead]
    next_cursor: str | None = None
