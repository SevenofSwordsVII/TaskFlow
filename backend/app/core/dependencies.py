"""Core FastAPI dependencies for database sessions and authentication."""

import uuid
from collections.abc import AsyncGenerator, Callable, Coroutine
from typing import Any

from fastapi import Depends, Header
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal
from app.core.exceptions import (
    BadRequestException,
    ForbiddenException,
    NotFoundException,
    UnauthorizedException,
)
from app.core.security import decode_access_token
from app.modules.kanban.models import Board, List, Task
from app.modules.organizations.models import Organization, OrganizationMember, OrganizationRole
from app.modules.projects.models import Project, ProjectMember, ProjectVisibility
from app.modules.users.models import User

ROLE_HIERARCHY: dict[str, int] = {
    "OWNER": 4,
    "ADMIN": 3,
    "MEMBER": 2,
    "VIEWER": 1,
}

oauth2_scheme = OAuth2PasswordBearer(
    tokenUrl="/api/v1/auth/token",
    auto_error=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Yield an asynchronous database session with automatic transaction management."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise


async def get_current_user(
    token: str | None = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Validate Bearer JWT access token statelessly and load active user entity."""
    if not token:
        raise UnauthorizedException(
            code="UNAUTHORIZED",
            message="Not authenticated.",
        )

    try:
        payload = decode_access_token(token)
    except Exception as exc:
        err_msg = str(exc)
        if "expired" in err_msg.lower():
            raise UnauthorizedException(
                code="TOKEN_EXPIRED",
                message="Access token has expired.",
            ) from exc
        raise UnauthorizedException(
            code="INVALID_TOKEN",
            message="Could not validate credentials.",
        ) from exc

    token_type = payload.get("type")
    if token_type != "access":
        raise UnauthorizedException(
            code="INVALID_TOKEN",
            message="Invalid token type.",
        )

    user_id_str = payload.get("sub")
    if not user_id_str:
        raise UnauthorizedException(
            code="INVALID_TOKEN",
            message="Token subject missing.",
        )

    try:
        user_uuid = uuid.UUID(user_id_str)
    except ValueError as exc:
        raise UnauthorizedException(
            code="INVALID_TOKEN",
            message="Malformed user ID in token.",
        ) from exc

    stmt = select(User).where(
        User.id == user_uuid,
        User.deleted_at.is_(None),
    )
    user = (await db.execute(stmt)).scalar_one_or_none()

    if not user:
        raise UnauthorizedException(
            code="USER_NOT_FOUND",
            message="User not found or deleted.",
        )

    return user


async def get_current_active_user(
    current_user: User = Depends(get_current_user),
) -> User:
    """Ensure the authenticated user account is active."""
    if not current_user.is_active:
        raise UnauthorizedException(
            code="ACCOUNT_INACTIVE",
            message="Inactive user account.",
        )
    return current_user


def require_org_role(
    min_role: str | OrganizationRole = OrganizationRole.MEMBER,
) -> Callable[..., Coroutine[Any, Any, OrganizationMember]]:
    """Enforce organization-level RBAC and tenant concealment (404 on non-membership)."""
    min_role_str = min_role.value if isinstance(min_role, OrganizationRole) else str(min_role)

    async def _dependency(
        organization_id: uuid.UUID,
        current_user: User = Depends(get_current_active_user),
        db: AsyncSession = Depends(get_db),
    ) -> OrganizationMember:
        stmt = select(OrganizationMember).where(
            OrganizationMember.organization_id == organization_id,
            OrganizationMember.user_id == current_user.id,
        )
        member = (await db.execute(stmt)).scalar_one_or_none()
        if not member:
            raise NotFoundException(
                code="ORGANIZATION_NOT_FOUND",
                message="Organization not found.",
            )

        user_level = ROLE_HIERARCHY.get(member.role, 0)
        required_level = ROLE_HIERARCHY.get(min_role_str, 0)
        if user_level < required_level:
            raise ForbiddenException(
                code="INSUFFICIENT_ROLE",
                message=f"Action requires at least {min_role_str} role.",
            )

        return member

    return _dependency


async def check_project_access_for_project(
    project: Project,
    user: User,
    db: AsyncSession,
    min_role: str = "VIEWER",
    conceal_code: str = "PROJECT_NOT_FOUND",
    conceal_message: str = "Project not found.",
) -> Project:
    """Enforce tenant isolation, restricted visibility, and role hierarchy for a project."""
    org_member_stmt = select(OrganizationMember).where(
        OrganizationMember.organization_id == project.organization_id,
        OrganizationMember.user_id == user.id,
    )
    org_member = (await db.execute(org_member_stmt)).scalar_one_or_none()
    if not org_member:
        raise NotFoundException(
            code=conceal_code,
            message=conceal_message,
        )

    if project.visibility == ProjectVisibility.RESTRICTED:
        org_level = ROLE_HIERARCHY.get(org_member.role, 0)
        if org_level < ROLE_HIERARCHY["ADMIN"]:
            pm_stmt = select(ProjectMember).where(
                ProjectMember.project_id == project.id,
                ProjectMember.user_id == user.id,
            )
            pm = (await db.execute(pm_stmt)).scalar_one_or_none()
            if not pm:
                raise NotFoundException(
                    code=conceal_code,
                    message=conceal_message,
                )

    user_level = ROLE_HIERARCHY.get(org_member.role, 0)
    required_level = ROLE_HIERARCHY.get(min_role, 0)
    if user_level < required_level:
        raise ForbiddenException(
            code="INSUFFICIENT_ROLE",
            message=f"Action requires at least {min_role} role.",
        )

    return project


async def get_accessible_project(
    project_id: uuid.UUID,
    user: User,
    db: AsyncSession,
    min_role: str = "VIEWER",
) -> Project:
    """Load project enforcing tenant boundaries, project membership, and role permissions."""
    stmt = select(Project).where(
        Project.id == project_id,
        Project.deleted_at.is_(None),
    )
    project = (await db.execute(stmt)).scalar_one_or_none()
    if not project:
        raise NotFoundException(
            code="PROJECT_NOT_FOUND",
            message="Project not found.",
        )
    return await check_project_access_for_project(
        project=project,
        user=user,
        db=db,
        min_role=min_role,
        conceal_code="PROJECT_NOT_FOUND",
        conceal_message="Project not found.",
    )


async def get_accessible_board(
    board_id: uuid.UUID,
    user: User,
    db: AsyncSession,
    min_role: str = "VIEWER",
) -> Board:
    """Load board joined with project, enforcing tenant boundaries and access permissions."""
    stmt = (
        select(Board, Project)
        .join(Project, Project.id == Board.project_id)
        .where(
            Board.id == board_id,
            Board.deleted_at.is_(None),
            Project.deleted_at.is_(None),
        )
    )
    row = (await db.execute(stmt)).one_or_none()
    if not row:
        raise NotFoundException(
            code="BOARD_NOT_FOUND",
            message="Board does not exist or access denied.",
        )
    board, project = row
    await check_project_access_for_project(
        project=project,
        user=user,
        db=db,
        min_role=min_role,
        conceal_code="BOARD_NOT_FOUND",
        conceal_message="Board does not exist or access denied.",
    )
    return board


async def get_accessible_list(
    list_id: uuid.UUID,
    user: User,
    db: AsyncSession,
    min_role: str = "VIEWER",
) -> List:
    """Load list joined with project, enforcing tenant boundaries and access permissions."""
    stmt = (
        select(List, Project)
        .join(Project, Project.id == List.project_id)
        .where(
            List.id == list_id,
            List.deleted_at.is_(None),
            Project.deleted_at.is_(None),
        )
    )
    row = (await db.execute(stmt)).one_or_none()
    if not row:
        raise NotFoundException(
            code="LIST_NOT_FOUND",
            message="List does not exist or access denied.",
        )
    lst, project = row
    await check_project_access_for_project(
        project=project,
        user=user,
        db=db,
        min_role=min_role,
        conceal_code="LIST_NOT_FOUND",
        conceal_message="List does not exist or access denied.",
    )
    return lst


async def get_accessible_task(
    task_id: uuid.UUID,
    user: User,
    db: AsyncSession,
    min_role: str = "VIEWER",
) -> Task:
    """Load task joined with project, enforcing tenant boundaries and access permissions."""
    stmt = (
        select(Task, Project)
        .join(Project, Project.id == Task.project_id)
        .where(
            Task.id == task_id,
            Task.deleted_at.is_(None),
            Project.deleted_at.is_(None),
        )
    )
    row = (await db.execute(stmt)).one_or_none()
    if not row:
        raise NotFoundException(
            code="TASK_NOT_FOUND",
            message="Task does not exist or access denied.",
        )
    task, project = row
    await check_project_access_for_project(
        project=project,
        user=user,
        db=db,
        min_role=min_role,
        conceal_code="TASK_NOT_FOUND",
        conceal_message="Task does not exist or access denied.",
    )
    return task


def require_project_access(
    min_role: str = "VIEWER",
) -> Callable[..., Coroutine[Any, Any, Project]]:
    """Enforce project access, restricted visibility gating, and tenant concealment."""

    async def _dependency(
        project_id: uuid.UUID,
        current_user: User = Depends(get_current_active_user),
        db: AsyncSession = Depends(get_db),
    ) -> Project:
        return await get_accessible_project(project_id, current_user, db, min_role)

    return _dependency


def require_board_access(
    min_role: str = "VIEWER",
) -> Callable[..., Coroutine[Any, Any, Board]]:
    """Enforce board access, parent project visibility gating, and tenant concealment."""

    async def _dependency(
        board_id: uuid.UUID,
        current_user: User = Depends(get_current_active_user),
        db: AsyncSession = Depends(get_db),
    ) -> Board:
        return await get_accessible_board(board_id, current_user, db, min_role)

    return _dependency


def require_list_access(
    min_role: str = "VIEWER",
) -> Callable[..., Coroutine[Any, Any, List]]:
    """Enforce list access, parent project visibility gating, and tenant concealment."""

    async def _dependency(
        list_id: uuid.UUID,
        current_user: User = Depends(get_current_active_user),
        db: AsyncSession = Depends(get_db),
    ) -> List:
        return await get_accessible_list(list_id, current_user, db, min_role)

    return _dependency


def require_task_access(
    min_role: str = "VIEWER",
) -> Callable[..., Coroutine[Any, Any, Task]]:
    """Enforce task access, parent project visibility gating, and tenant concealment."""

    async def _dependency(
        task_id: uuid.UUID,
        current_user: User = Depends(get_current_active_user),
        db: AsyncSession = Depends(get_db),
    ) -> Task:
        return await get_accessible_task(task_id, current_user, db, min_role)

    return _dependency


async def get_current_tenant(
    x_organization_id: str | None = Header(default=None, alias="X-Organization-Id"),
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> Organization:
    """Extract and validate tenant workspace context from X-Organization-Id header."""
    if not x_organization_id:
        raise BadRequestException(
            code="MISSING_TENANT_HEADER",
            message="X-Organization-Id header is required.",
        )
    try:
        org_uuid = uuid.UUID(x_organization_id)
    except ValueError as exc:
        raise BadRequestException(
            code="INVALID_TENANT_ID",
            message="Invalid UUID in X-Organization-Id header.",
        ) from exc

    stmt = select(Organization).where(
        Organization.id == org_uuid,
        Organization.deleted_at.is_(None),
    )
    org = (await db.execute(stmt)).scalar_one_or_none()
    if not org:
        raise NotFoundException(
            code="ORGANIZATION_NOT_FOUND",
            message="Organization not found.",
        )

    member_stmt = select(OrganizationMember).where(
        OrganizationMember.organization_id == org_uuid,
        OrganizationMember.user_id == current_user.id,
    )
    member = (await db.execute(member_stmt)).scalar_one_or_none()
    if not member:
        raise NotFoundException(
            code="ORGANIZATION_NOT_FOUND",
            message="Organization not found.",
        )

    return org
