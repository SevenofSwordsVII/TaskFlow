"""Audit log service for immutable append-only governance recording."""

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.audit_logs.models import AuditLog, AuditTargetType
from app.modules.audit_logs.schemas import AuditLogListResponse, AuditLogRead
from app.modules.users.models import User
from app.modules.users.schemas import UserBrief


class AuditLogService:
    """Service handling append-only governance and security event auditing."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def record_event(
        self,
        organization_id: uuid.UUID,
        action: str,
        target_type: AuditTargetType,
        actor_id: uuid.UUID | None = None,
        target_id: uuid.UUID | None = None,
        payload: dict[str, Any] | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> AuditLog:
        """Write an immutable audit log record. Task moves are strictly excluded."""
        log_entry = AuditLog(
            id=uuid.uuid4(),
            organization_id=organization_id,
            actor_id=actor_id,
            action=action,
            target_type=target_type,
            target_id=target_id,
            payload=payload,
            ip_address=ip_address,
            user_agent=user_agent,
        )
        self.db.add(log_entry)
        await self.db.commit()
        await self.db.refresh(log_entry)
        return log_entry

    async def list_organization_audit_logs(
        self,
        organization_id: uuid.UUID,
        limit: int = 100,
    ) -> AuditLogListResponse:
        """Retrieve organization governance audit logs ordered chronologically reverse."""
        stmt = (
            select(AuditLog, User)
            .outerjoin(User, User.id == AuditLog.actor_id)
            .where(AuditLog.organization_id == organization_id)
            .order_by(AuditLog.created_at.desc())
            .limit(limit)
        )
        rows = (await self.db.execute(stmt)).all()

        items = [
            AuditLogRead(
                id=log.id,
                organization_id=log.organization_id,
                actor_id=log.actor_id,
                action=log.action,
                target_type=(
                    log.target_type.value
                    if hasattr(log.target_type, "value")
                    else str(log.target_type)
                ),
                target_id=log.target_id,
                payload=log.payload,
                ip_address=log.ip_address,
                user_agent=log.user_agent,
                created_at=log.created_at,
                actor=UserBrief.model_validate(u) if u else None,
            )
            for log, u in rows
        ]

        return AuditLogListResponse(items=items)
