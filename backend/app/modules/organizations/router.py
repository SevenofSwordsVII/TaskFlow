"""Organizations API router defining workspace creation, memberships, invitations, and RBAC."""

import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import (
    get_current_active_user,
    get_db,
    require_org_role,
)
from app.modules.organizations.models import OrganizationMember, OrganizationRole
from app.modules.organizations.schemas import (
    InvitationAcceptRequest,
    InvitationCreate,
    InvitationRead,
    MemberRoleUpdateRequest,
    OrganizationCreate,
    OrganizationMemberListResponse,
    OrganizationMemberRead,
    OrganizationRead,
    TransferOwnershipRequest,
)
from app.modules.organizations.service import OrganizationService
from app.modules.users.models import User

router = APIRouter(prefix="/organizations", tags=["organizations"])


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=OrganizationRead,
    summary="Create a new organization workspace",
)
async def create_organization(
    payload: OrganizationCreate,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> OrganizationRead:
    """Create a new tenant organization workspace and assign the creator as OWNER."""
    service = OrganizationService(db)
    return await service.create_organization(payload, creator=current_user)


@router.get(
    "",
    response_model=list[OrganizationRead],
    summary="List caller's organizations",
)
async def list_organizations(
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> list[OrganizationRead]:
    """Retrieve all organizations the current authenticated user belongs to."""
    service = OrganizationService(db)
    return await service.list_user_organizations(user=current_user)


@router.post(
    "/invitations/accept",
    response_model=OrganizationRead,
    summary="Accept member invitation",
)
async def accept_invitation(
    payload: InvitationAcceptRequest,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> OrganizationRead:
    """Accept invitation via token and join organization."""
    service = OrganizationService(db)
    return await service.accept_invitation(payload.token, user=current_user)


@router.get(
    "/{organization_id}/members",
    response_model=OrganizationMemberListResponse,
    summary="List organization members",
)
async def list_members(
    organization_id: uuid.UUID,
    member: OrganizationMember = Depends(require_org_role(OrganizationRole.VIEWER)),
    db: AsyncSession = Depends(get_db),
) -> OrganizationMemberListResponse:
    """List members of organization with roles. Conceals tenant with 404 for non-members."""
    service = OrganizationService(db)
    return await service.list_members(organization_id)


@router.patch(
    "/{organization_id}/members/{user_id}",
    response_model=OrganizationMemberRead,
    summary="Update organization member role",
)
async def update_member_role(
    organization_id: uuid.UUID,
    user_id: uuid.UUID,
    payload: MemberRoleUpdateRequest,
    actor_member: OrganizationMember = Depends(require_org_role(OrganizationRole.ADMIN)),
    db: AsyncSession = Depends(get_db),
) -> OrganizationMemberRead:
    """Update role of organization member. Requires ADMIN or OWNER."""
    service = OrganizationService(db)
    actor_role_str = (
        actor_member.role.value if hasattr(actor_member.role, "value") else str(actor_member.role)
    )
    return await service.update_member_role(
        organization_id=organization_id,
        user_id=user_id,
        new_role=payload.role,
        actor_role=actor_role_str,
    )


@router.delete(
    "/{organization_id}/members/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove member from organization",
)
async def remove_member(
    organization_id: uuid.UUID,
    user_id: uuid.UUID,
    actor_member: OrganizationMember = Depends(require_org_role(OrganizationRole.ADMIN)),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Remove member and atomically unassign their tasks in this organization."""
    service = OrganizationService(db)
    actor_role_str = (
        actor_member.role.value if hasattr(actor_member.role, "value") else str(actor_member.role)
    )
    await service.remove_member(
        organization_id=organization_id,
        user_id=user_id,
        actor_role=actor_role_str,
    )


@router.post(
    "/{organization_id}/transfer-ownership",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Transfer organization ownership",
)
async def transfer_ownership(
    organization_id: uuid.UUID,
    payload: TransferOwnershipRequest,
    current_user: User = Depends(get_current_active_user),
    owner_member: OrganizationMember = Depends(require_org_role(OrganizationRole.OWNER)),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Transfer organization ownership. Strictly restricted to current OWNER."""
    service = OrganizationService(db)
    await service.transfer_ownership(
        organization_id=organization_id,
        current_owner_id=current_user.id,
        new_owner_id=payload.new_owner_user_id,
    )


@router.post(
    "/{organization_id}/invitations",
    status_code=status.HTTP_201_CREATED,
    response_model=InvitationRead,
    summary="Create member invitation",
)
async def create_invitation(
    organization_id: uuid.UUID,
    payload: InvitationCreate,
    current_user: User = Depends(get_current_active_user),
    admin_member: OrganizationMember = Depends(require_org_role(OrganizationRole.ADMIN)),
    db: AsyncSession = Depends(get_db),
) -> InvitationRead:
    """Invite a new member via email. Requires ADMIN or OWNER."""
    service = OrganizationService(db)
    return await service.create_invitation(
        organization_id=organization_id,
        payload=payload,
        inviter=current_user,
    )


@router.get(
    "/{organization_id}/invitations",
    response_model=list[InvitationRead],
    summary="List active pending invitations",
)
async def list_invitations(
    organization_id: uuid.UUID,
    admin_member: OrganizationMember = Depends(require_org_role(OrganizationRole.ADMIN)),
    db: AsyncSession = Depends(get_db),
) -> list[InvitationRead]:
    """List active pending invitations. Requires ADMIN or OWNER."""
    service = OrganizationService(db)
    return await service.list_invitations(organization_id)


@router.delete(
    "/{organization_id}/invitations/{invitation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Revoke pending invitation",
)
async def revoke_invitation(
    organization_id: uuid.UUID,
    invitation_id: uuid.UUID,
    admin_member: OrganizationMember = Depends(require_org_role(OrganizationRole.ADMIN)),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Revoke invitation. Requires ADMIN or OWNER."""
    service = OrganizationService(db)
    await service.revoke_invitation(
        organization_id=organization_id,
        invitation_id=invitation_id,
    )
