"""Audit logs API router for organization governance inspection."""

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_db, require_org_role
from app.modules.audit_logs.schemas import AuditLogListResponse
from app.modules.audit_logs.service import AuditLogService
from app.modules.organizations.models import OrganizationMember, OrganizationRole

router = APIRouter(tags=["audit_logs"])


@router.get(
    "/organizations/{organization_id}/audit-logs",
    response_model=AuditLogListResponse,
    summary="List organization governance audit logs",
)
async def list_organization_audit_logs(
    organization_id: uuid.UUID,
    admin_member: OrganizationMember = Depends(require_org_role(OrganizationRole.ADMIN)),
    db: AsyncSession = Depends(get_db),
) -> AuditLogListResponse:
    """Retrieve immutable audit trail for the organization. Restricted to OWNER and ADMIN."""
    service = AuditLogService(db)
    return await service.list_organization_audit_logs(organization_id=organization_id)
