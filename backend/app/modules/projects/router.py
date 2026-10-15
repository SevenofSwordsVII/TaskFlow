"""Project API router handling project CRUD and project membership management."""

import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import (
    ROLE_HIERARCHY,
    get_current_active_user,
    get_db,
    require_org_role,
    require_project_access,
)
from app.modules.organizations.models import OrganizationMember, OrganizationRole
from app.modules.projects.models import Project
from app.modules.projects.schemas import (
    ProjectCreate,
    ProjectMemberCreate,
    ProjectMemberListResponse,
    ProjectMemberRead,
    ProjectRead,
    ProjectUpdate,
)
from app.modules.projects.service import ProjectService
from app.modules.users.models import User

router = APIRouter(tags=["projects"])


@router.post(
    "/organizations/{organization_id}/projects",
    status_code=status.HTTP_201_CREATED,
    response_model=ProjectRead,
    summary="Create project in organization",
)
async def create_project(
    organization_id: uuid.UUID,
    payload: ProjectCreate,
    member: OrganizationMember = Depends(require_org_role(OrganizationRole.ADMIN)),
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> ProjectRead:
    """Create a new project within an organization. Requires ADMIN or OWNER role."""
    service = ProjectService(db)
    return await service.create_project(organization_id, payload, creator=current_user)


@router.get(
    "/organizations/{organization_id}/projects",
    response_model=list[ProjectRead],
    summary="List visible projects in organization",
)
async def list_projects(
    organization_id: uuid.UUID,
    member: OrganizationMember = Depends(require_org_role(OrganizationRole.VIEWER)),
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> list[ProjectRead]:
    """List projects in organization visible to current user."""
    service = ProjectService(db)
    is_admin = ROLE_HIERARCHY.get(member.role, 0) >= ROLE_HIERARCHY["ADMIN"]
    return await service.list_projects(organization_id, current_user, is_org_admin=is_admin)


@router.get(
    "/projects/{project_id}",
    response_model=ProjectRead,
    summary="Get project by ID",
)
async def get_project(
    project_id: uuid.UUID,
    project: Project = Depends(require_project_access("VIEWER")),
    db: AsyncSession = Depends(get_db),
) -> ProjectRead:
    """Fetch project details. Conceals non-accessible projects with 404."""
    service = ProjectService(db)
    return await service.get_project(project)


@router.patch(
    "/projects/{project_id}",
    response_model=ProjectRead,
    summary="Update project details",
)
async def update_project(
    project_id: uuid.UUID,
    payload: ProjectUpdate,
    project: Project = Depends(require_project_access("ADMIN")),
    db: AsyncSession = Depends(get_db),
) -> ProjectRead:
    """Update project details. Requires ADMIN or OWNER role."""
    service = ProjectService(db)
    return await service.update_project(project, payload)


@router.delete(
    "/projects/{project_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Soft-delete project",
)
async def delete_project(
    project_id: uuid.UUID,
    project: Project = Depends(require_project_access("ADMIN")),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Soft-delete project. Requires ADMIN or OWNER role."""
    service = ProjectService(db)
    await service.delete_project(project)


@router.get(
    "/projects/{project_id}/members",
    response_model=ProjectMemberListResponse,
    summary="List project members",
)
async def list_project_members(
    project_id: uuid.UUID,
    project: Project = Depends(require_project_access("VIEWER")),
    db: AsyncSession = Depends(get_db),
) -> ProjectMemberListResponse:
    """List members assigned to restricted project."""
    service = ProjectService(db)
    items = await service.list_project_members(project_id)
    return ProjectMemberListResponse(items=items)


@router.post(
    "/projects/{project_id}/members",
    status_code=status.HTTP_201_CREATED,
    response_model=ProjectMemberRead,
    summary="Add member to project",
)
async def add_project_member(
    project_id: uuid.UUID,
    payload: ProjectMemberCreate,
    project: Project = Depends(require_project_access("ADMIN")),
    db: AsyncSession = Depends(get_db),
) -> ProjectMemberRead:
    """Add member to project. User must belong to the organization."""
    service = ProjectService(db)
    return await service.add_project_member(project, payload)


@router.delete(
    "/projects/{project_id}/members/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove member from project",
)
async def remove_project_member(
    project_id: uuid.UUID,
    user_id: uuid.UUID,
    project: Project = Depends(require_project_access("ADMIN")),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Remove member from project."""
    service = ProjectService(db)
    await service.remove_project_member(project_id, user_id)
