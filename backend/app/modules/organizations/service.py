"""Organization domain service managing tenant workspaces, memberships, and invitations."""

import hashlib
import secrets
import uuid
from datetime import timedelta

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.base import utc_now
from app.core.exceptions import (
    BadRequestException,
    ConflictException,
    ForbiddenException,
    NotFoundException,
)
from app.modules.audit_logs.models import AuditLog, AuditTargetType
from app.modules.kanban.models import Task
from app.modules.organizations.models import (
    Organization,
    OrganizationInvitation,
    OrganizationMember,
    OrganizationRole,
)
from app.modules.organizations.schemas import (
    InvitationCreate,
    InvitationRead,
    OrganizationCreate,
    OrganizationMemberListResponse,
    OrganizationMemberRead,
    OrganizationRead,
)
from app.modules.projects.models import Project, ProjectMember
from app.modules.users.models import User
from app.modules.users.schemas import UserBrief


class OrganizationService:
    """Service encapsulating organization workspace creation, invitations, and membership."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def create_organization(
        self,
        payload: OrganizationCreate,
        creator: User,
    ) -> OrganizationRead:
        """Atomically create organization and assign creator as OWNER."""
        clean_slug = payload.slug.strip().lower()

        stmt = select(Organization).where(
            Organization.slug == clean_slug,
            Organization.deleted_at.is_(None),
        )
        existing = (await self.db.execute(stmt)).scalar_one_or_none()
        if existing:
            raise ConflictException(
                code="ORGANIZATION_SLUG_EXISTS",
                message="Organization slug is already in use.",
            )

        now = utc_now()
        org = Organization(
            id=uuid.uuid4(),
            name=payload.name.strip(),
            slug=clean_slug,
            is_archived=False,
            created_at=now,
            updated_at=now,
        )
        self.db.add(org)
        await self.db.flush()

        member = OrganizationMember(
            id=uuid.uuid4(),
            organization_id=org.id,
            user_id=creator.id,
            role=OrganizationRole.OWNER,
        )
        self.db.add(member)
        await self.db.commit()
        await self.db.refresh(org)

        return OrganizationRead(
            id=org.id,
            name=org.name,
            slug=org.slug,
            is_archived=org.is_archived,
            created_at=org.created_at,
            updated_at=org.updated_at,
            role=OrganizationRole.OWNER.value,
        )

    async def list_user_organizations(self, user: User) -> list[OrganizationRead]:
        """List active organizations the user belongs to, including their role."""
        stmt = (
            select(Organization, OrganizationMember.role)
            .join(OrganizationMember, OrganizationMember.organization_id == Organization.id)
            .where(
                OrganizationMember.user_id == user.id,
                Organization.deleted_at.is_(None),
            )
            .order_by(Organization.created_at.desc())
        )
        result = await self.db.execute(stmt)
        rows = result.all()

        return [
            OrganizationRead(
                id=org.id,
                name=org.name,
                slug=org.slug,
                is_archived=org.is_archived,
                created_at=org.created_at,
                updated_at=org.updated_at,
                role=role.value if hasattr(role, "value") else str(role),
            )
            for org, role in rows
        ]

    async def list_members(
        self,
        organization_id: uuid.UUID,
    ) -> OrganizationMemberListResponse:
        """List all active members in an organization."""
        stmt = (
            select(OrganizationMember, User)
            .join(User, User.id == OrganizationMember.user_id)
            .where(OrganizationMember.organization_id == organization_id)
            .order_by(OrganizationMember.created_at.asc())
        )
        rows = (await self.db.execute(stmt)).all()
        items = []
        for member, user in rows:
            items.append(
                OrganizationMemberRead(
                    id=member.id,
                    organization_id=member.organization_id,
                    user_id=member.user_id,
                    role=member.role.value if hasattr(member.role, "value") else str(member.role),
                    created_at=member.created_at,
                    updated_at=member.updated_at,
                    user=UserBrief.model_validate(user),
                )
            )
        return OrganizationMemberListResponse(items=items)

    async def update_member_role(
        self,
        organization_id: uuid.UUID,
        user_id: uuid.UUID,
        new_role: OrganizationRole,
        actor_role: str,
    ) -> OrganizationMemberRead:
        """Update role of an organization member."""
        if new_role == OrganizationRole.OWNER:
            raise BadRequestException(
                code="INVALID_ROLE_ASSIGNMENT",
                message="Cannot assign OWNER role via role update; use ownership transfer.",
            )

        stmt = (
            select(OrganizationMember, User)
            .join(User, User.id == OrganizationMember.user_id)
            .where(
                OrganizationMember.organization_id == organization_id,
                OrganizationMember.user_id == user_id,
            )
        )
        row = (await self.db.execute(stmt)).one_or_none()
        if not row:
            raise NotFoundException(
                code="MEMBER_NOT_FOUND",
                message="Organization member not found.",
            )
        member, user = row

        if member.role == OrganizationRole.OWNER:
            raise ForbiddenException(
                code="CANNOT_DEMOTE_OWNER",
                message="Organization OWNER role cannot be modified directly.",
            )

        if member.role == OrganizationRole.ADMIN and actor_role != OrganizationRole.OWNER.value:
            raise ForbiddenException(
                code="INSUFFICIENT_PERMISSIONS",
                message="Only organization OWNER can modify an ADMIN role.",
            )

        member.role = new_role
        await self.db.commit()
        await self.db.refresh(member)

        return OrganizationMemberRead(
            id=member.id,
            organization_id=member.organization_id,
            user_id=member.user_id,
            role=member.role.value if hasattr(member.role, "value") else str(member.role),
            created_at=member.created_at,
            updated_at=member.updated_at,
            user=UserBrief.model_validate(user),
        )

    async def remove_member(
        self,
        organization_id: uuid.UUID,
        user_id: uuid.UUID,
        actor_role: str,
    ) -> None:
        """Remove member, atomically unassigning all their tasks in tenant."""
        stmt = select(OrganizationMember).where(
            OrganizationMember.organization_id == organization_id,
            OrganizationMember.user_id == user_id,
        )
        member = (await self.db.execute(stmt)).scalar_one_or_none()
        if not member:
            raise NotFoundException(
                code="MEMBER_NOT_FOUND",
                message="Organization member not found.",
            )

        if member.role == OrganizationRole.OWNER:
            raise ForbiddenException(
                code="CANNOT_REMOVE_OWNER",
                message="The organization owner cannot be removed.",
            )

        if member.role == OrganizationRole.ADMIN and actor_role != OrganizationRole.OWNER.value:
            raise ForbiddenException(
                code="INSUFFICIENT_PERMISSIONS",
                message="Only organization OWNER can remove an ADMIN.",
            )

        # 1. Unassign tasks in this organization
        await self.db.execute(
            update(Task)
            .where(
                Task.organization_id == organization_id,
                Task.assignee_id == user_id,
                Task.deleted_at.is_(None),
            )
            .values(assignee_id=None)
        )

        # 2. Remove project memberships in this organization's projects
        proj_subq = (
            select(Project.id).where(Project.organization_id == organization_id).scalar_subquery()
        )
        await self.db.execute(
            delete(ProjectMember).where(
                ProjectMember.project_id.in_(proj_subq),
                ProjectMember.user_id == user_id,
            )
        )

        # 3. Delete organization membership
        await self.db.delete(member)
        await self.db.commit()

    async def transfer_ownership(
        self,
        organization_id: uuid.UUID,
        current_owner_id: uuid.UUID,
        new_owner_id: uuid.UUID,
    ) -> None:
        """Transfer organization ownership atomically."""
        if current_owner_id == new_owner_id:
            return

        # Fetch new owner membership
        new_owner_stmt = select(OrganizationMember).where(
            OrganizationMember.organization_id == organization_id,
            OrganizationMember.user_id == new_owner_id,
        )
        new_owner_member = (await self.db.execute(new_owner_stmt)).scalar_one_or_none()
        if not new_owner_member:
            raise NotFoundException(
                code="TARGET_USER_NOT_MEMBER",
                message="Target user is not a member of this organization.",
            )

        # Fetch current owner membership
        curr_owner_stmt = select(OrganizationMember).where(
            OrganizationMember.organization_id == organization_id,
            OrganizationMember.user_id == current_owner_id,
        )
        curr_owner_member = (await self.db.execute(curr_owner_stmt)).scalar_one()

        curr_owner_member.role = OrganizationRole.ADMIN
        new_owner_member.role = OrganizationRole.OWNER
        await self.db.commit()

    async def create_invitation(
        self,
        organization_id: uuid.UUID,
        payload: InvitationCreate,
        inviter: User,
    ) -> InvitationRead:
        """Generate member invitation with SHA-256 token hash and 7-day expiration."""
        if payload.role == OrganizationRole.OWNER:
            raise BadRequestException(
                code="INVALID_ROLE_ASSIGNMENT",
                message="Cannot invite member with OWNER role; use ownership transfer.",
            )

        clean_email = payload.email.strip().lower()

        # Check if already a member
        user_stmt = select(User).where(User.email == clean_email, User.deleted_at.is_(None))
        existing_user = (await self.db.execute(user_stmt)).scalar_one_or_none()
        if existing_user:
            mem_stmt = select(OrganizationMember).where(
                OrganizationMember.organization_id == organization_id,
                OrganizationMember.user_id == existing_user.id,
            )
            if (await self.db.execute(mem_stmt)).scalar_one_or_none():
                raise ConflictException(
                    code="USER_ALREADY_MEMBER",
                    message="User is already a member of this organization.",
                )

        now = utc_now()
        # Check active pending invitation
        inv_stmt = select(OrganizationInvitation).where(
            OrganizationInvitation.organization_id == organization_id,
            OrganizationInvitation.email == clean_email,
            OrganizationInvitation.accepted_at.is_(None),
            OrganizationInvitation.revoked_at.is_(None),
            OrganizationInvitation.expired_at.is_(None),
        )
        pending_inv = (await self.db.execute(inv_stmt)).scalar_one_or_none()
        if pending_inv:
            if pending_inv.expires_at > now:
                raise ConflictException(
                    code="PENDING_INVITATION_EXISTS",
                    message="An active invitation already exists for this email address.",
                )
            # Expired in practice: finalize expiration atomically to release unique index
            pending_inv.expired_at = now
            await self.db.flush()

        raw_token = secrets.token_urlsafe(32)
        token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()

        invitation = OrganizationInvitation(
            id=uuid.uuid4(),
            organization_id=organization_id,
            email=clean_email,
            role=payload.role,
            token_hash=token_hash,
            invited_by_id=inviter.id,
            expires_at=now + timedelta(days=7),
            created_at=now,
        )
        self.db.add(invitation)
        await self.db.commit()
        await self.db.refresh(invitation)

        return InvitationRead(
            id=invitation.id,
            organization_id=invitation.organization_id,
            email=invitation.email,
            role=invitation.role.value
            if hasattr(invitation.role, "value")
            else str(invitation.role),
            invited_by_id=invitation.invited_by_id,
            expires_at=invitation.expires_at,
            created_at=invitation.created_at,
            invitation_token=raw_token,
        )

    async def list_invitations(
        self,
        organization_id: uuid.UUID,
    ) -> list[InvitationRead]:
        """List active pending invitations for organization."""
        now = utc_now()
        stmt = (
            select(OrganizationInvitation)
            .where(
                OrganizationInvitation.organization_id == organization_id,
                OrganizationInvitation.accepted_at.is_(None),
                OrganizationInvitation.revoked_at.is_(None),
                OrganizationInvitation.expired_at.is_(None),
                OrganizationInvitation.expires_at > now,
            )
            .order_by(OrganizationInvitation.created_at.desc())
        )
        invs = (await self.db.execute(stmt)).scalars().all()
        return [
            InvitationRead(
                id=i.id,
                organization_id=i.organization_id,
                email=i.email,
                role=i.role.value if hasattr(i.role, "value") else str(i.role),
                invited_by_id=i.invited_by_id,
                expires_at=i.expires_at,
                created_at=i.created_at,
            )
            for i in invs
        ]

    async def revoke_invitation(
        self,
        organization_id: uuid.UUID,
        invitation_id: uuid.UUID,
    ) -> None:
        """Revoke a pending invitation."""
        stmt = (
            select(OrganizationInvitation)
            .where(
                OrganizationInvitation.id == invitation_id,
                OrganizationInvitation.organization_id == organization_id,
            )
            .with_for_update()
        )
        inv = (await self.db.execute(stmt)).scalar_one_or_none()
        if not inv or inv.revoked_at or inv.accepted_at:
            raise NotFoundException(
                code="INVITATION_NOT_FOUND",
                message="Invitation not found or already concluded.",
            )
        inv.revoked_at = utc_now()
        await self.db.commit()

    async def accept_invitation(
        self,
        raw_token: str,
        user: User,
    ) -> OrganizationRead:
        """Accept invitation using token, assign member role atomically."""
        token_hash = hashlib.sha256(raw_token.strip().encode("utf-8")).hexdigest()
        now = utc_now()

        stmt = (
            select(OrganizationInvitation)
            .where(OrganizationInvitation.token_hash == token_hash)
            .with_for_update()
        )
        inv = (await self.db.execute(stmt)).scalar_one_or_none()
        if not inv:
            raise NotFoundException(
                code="INVITATION_NOT_FOUND",
                message="Invalid or missing invitation token.",
            )

        if inv.accepted_at is not None:
            raise BadRequestException(
                code="INVITATION_ALREADY_ACCEPTED",
                message="Invitation has already been accepted.",
            )

        if inv.revoked_at is not None:
            raise BadRequestException(
                code="INVITATION_REVOKED",
                message="Invitation has been revoked.",
            )

        if inv.expired_at is not None or inv.expires_at < now:
            if inv.expired_at is None:
                inv.expired_at = now
                await self.db.commit()
            raise BadRequestException(
                code="INVITATION_EXPIRED",
                message="Invitation has expired.",
            )

        # 5. Email Equality Verification
        if user.email.strip().lower() != inv.email.strip().lower():
            raise ForbiddenException(
                code="INVITATION_EMAIL_MISMATCH",
                message="Authenticated email does not match invitation recipient email.",
            )

        # Defense-in-depth: OWNER role cannot be granted via invitation
        if (
            inv.role == OrganizationRole.OWNER
            or (hasattr(inv.role, "value") and inv.role.value == "OWNER")
            or str(inv.role) == "OWNER"
        ):
            raise ForbiddenException(
                code="INVALID_ROLE_ASSIGNMENT",
                message="Cannot accept invitation for OWNER role; use ownership transfer.",
            )

        # 6. Check existing membership
        mem_stmt = select(OrganizationMember).where(
            OrganizationMember.organization_id == inv.organization_id,
            OrganizationMember.user_id == user.id,
        )
        existing_mem = (await self.db.execute(mem_stmt)).scalar_one_or_none()
        if existing_mem:
            raise ConflictException(
                code="ALREADY_MEMBER",
                message="User is already an active member of this organization.",
            )

        member = OrganizationMember(
            id=uuid.uuid4(),
            organization_id=inv.organization_id,
            user_id=user.id,
            role=inv.role,
        )
        self.db.add(member)

        inv.accepted_at = now

        # 8. Emit audit log INVITATION_ACCEPTED
        audit_entry = AuditLog(
            id=uuid.uuid4(),
            organization_id=inv.organization_id,
            actor_id=user.id,
            action="INVITATION_ACCEPTED",
            target_type=AuditTargetType.MEMBER,
            target_id=member.id,
            payload={
                "email": inv.email,
                "role": inv.role.value if hasattr(inv.role, "value") else str(inv.role),
            },
            created_at=now,
        )
        self.db.add(audit_entry)

        await self.db.commit()

        org_stmt = select(Organization).where(Organization.id == inv.organization_id)
        org = (await self.db.execute(org_stmt)).scalar_one()

        return OrganizationRead(
            id=org.id,
            name=org.name,
            slug=org.slug,
            is_archived=org.is_archived,
            created_at=org.created_at,
            updated_at=org.updated_at,
            role=inv.role.value if hasattr(inv.role, "value") else str(inv.role),
        )
