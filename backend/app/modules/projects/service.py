"""Project domain service handling multi-tenant projects and access control."""

import uuid

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.base import utc_now
from app.core.exceptions import (
    BadRequestException,
    ConflictException,
    NotFoundException,
)
from app.modules.organizations.models import OrganizationMember
from app.modules.projects.models import (
    Project,
    ProjectMember,
    ProjectRole,
    ProjectVisibility,
)
from app.modules.projects.schemas import (
    ProjectCreate,
    ProjectMemberCreate,
    ProjectMemberRead,
    ProjectRead,
    ProjectUpdate,
)
from app.modules.users.models import User
from app.modules.users.schemas import UserBrief


class ProjectService:
    """Service handling project lifecycles, restricted visibility, and project members."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def create_project(
        self,
        organization_id: uuid.UUID,
        payload: ProjectCreate,
        creator: User,
    ) -> ProjectRead:
        """Create a new project within an organization, enforcing key uniqueness."""
        stmt = select(Project).where(
            Project.organization_id == organization_id,
            Project.key == payload.key,
            Project.deleted_at.is_(None),
        )
        existing = (await self.db.execute(stmt)).scalar_one_or_none()
        if existing:
            raise ConflictException(
                code="PROJECT_KEY_EXISTS",
                message=f"Project with key '{payload.key}' already exists in this organization.",
            )

        project = Project(
            id=uuid.uuid4(),
            organization_id=organization_id,
            name=payload.name,
            key=payload.key,
            description=payload.description,
            visibility=payload.visibility,
            is_archived=False,
            created_by_id=creator.id,
        )
        self.db.add(project)

        # For RESTRICTED projects, add the creator as PROJECT_ADMIN
        if payload.visibility == ProjectVisibility.RESTRICTED:
            pm = ProjectMember(
                id=uuid.uuid4(),
                project_id=project.id,
                user_id=creator.id,
                project_role=ProjectRole.PROJECT_ADMIN,
            )
            self.db.add(pm)

        await self.db.commit()
        await self.db.refresh(project)
        return ProjectRead.model_validate(project)

    async def list_projects(
        self,
        organization_id: uuid.UUID,
        user: User,
        is_org_admin: bool,
    ) -> list[ProjectRead]:
        """List active projects visible to user (public or member-assigned)."""
        if is_org_admin:
            stmt = (
                select(Project)
                .where(
                    Project.organization_id == organization_id,
                    Project.deleted_at.is_(None),
                )
                .order_by(Project.created_at.asc())
            )
        else:
            # Subquery or join for project memberships
            stmt = (
                select(Project)
                .outerjoin(
                    ProjectMember,
                    and_(
                        ProjectMember.project_id == Project.id,
                        ProjectMember.user_id == user.id,
                    ),
                )
                .where(
                    Project.organization_id == organization_id,
                    Project.deleted_at.is_(None),
                    or_(
                        Project.visibility == ProjectVisibility.ORG_PUBLIC,
                        ProjectMember.id.is_not(None),
                    ),
                )
                .order_by(Project.created_at.asc())
            )

        results = (await self.db.execute(stmt)).scalars().all()
        return [ProjectRead.model_validate(p) for p in results]

    async def get_project(self, project: Project) -> ProjectRead:
        """Return validated project entity."""
        return ProjectRead.model_validate(project)

    async def update_project(
        self,
        project: Project,
        payload: ProjectUpdate,
    ) -> ProjectRead:
        """Update mutable project fields."""
        if payload.name is not None:
            project.name = payload.name
        if payload.description is not None:
            project.description = payload.description
        if payload.visibility is not None:
            project.visibility = payload.visibility
        if payload.is_archived is not None:
            project.is_archived = payload.is_archived

        await self.db.commit()
        await self.db.refresh(project)
        return ProjectRead.model_validate(project)

    async def delete_project(self, project: Project) -> None:
        """Soft-delete project."""
        project.deleted_at = utc_now()
        await self.db.commit()

    async def list_project_members(
        self,
        project_id: uuid.UUID,
    ) -> list[ProjectMemberRead]:
        """List explicit members of a project."""
        stmt = (
            select(ProjectMember, User)
            .join(User, User.id == ProjectMember.user_id)
            .where(ProjectMember.project_id == project_id)
            .order_by(ProjectMember.created_at.asc())
        )
        rows = (await self.db.execute(stmt)).all()
        items = []
        for pm, user in rows:
            items.append(
                ProjectMemberRead(
                    id=pm.id,
                    project_id=pm.project_id,
                    user_id=pm.user_id,
                    project_role=pm.project_role,
                    created_at=pm.created_at,
                    user=UserBrief.model_validate(user),
                )
            )
        return items

    async def add_project_member(
        self,
        project: Project,
        payload: ProjectMemberCreate,
    ) -> ProjectMemberRead:
        """Add member to restricted project, validating organization membership."""
        # 1. Validate organization membership
        org_stmt = select(OrganizationMember).where(
            OrganizationMember.organization_id == project.organization_id,
            OrganizationMember.user_id == payload.user_id,
        )
        org_member = (await self.db.execute(org_stmt)).scalar_one_or_none()
        if not org_member:
            raise BadRequestException(
                code="USER_NOT_ORG_MEMBER",
                message="User is not a member of this organization.",
            )

        # 2. Check duplicate
        pm_stmt = select(ProjectMember).where(
            ProjectMember.project_id == project.id,
            ProjectMember.user_id == payload.user_id,
        )
        existing_pm = (await self.db.execute(pm_stmt)).scalar_one_or_none()
        if existing_pm:
            raise ConflictException(
                code="MEMBER_ALREADY_EXISTS",
                message="User is already a member of this project.",
            )

        pm = ProjectMember(
            id=uuid.uuid4(),
            project_id=project.id,
            user_id=payload.user_id,
            project_role=payload.project_role,
        )
        self.db.add(pm)
        await self.db.commit()
        await self.db.refresh(pm)

        user_stmt = select(User).where(User.id == payload.user_id)
        user = (await self.db.execute(user_stmt)).scalar_one()

        return ProjectMemberRead(
            id=pm.id,
            project_id=pm.project_id,
            user_id=pm.user_id,
            project_role=pm.project_role,
            created_at=pm.created_at,
            user=UserBrief.model_validate(user),
        )

    async def remove_project_member(
        self,
        project_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> None:
        """Remove member from project."""
        stmt = select(ProjectMember).where(
            ProjectMember.project_id == project_id,
            ProjectMember.user_id == user_id,
        )
        pm = (await self.db.execute(stmt)).scalar_one_or_none()
        if not pm:
            raise NotFoundException(
                code="MEMBER_NOT_FOUND",
                message="Project member not found.",
            )
        await self.db.delete(pm)
        await self.db.commit()
