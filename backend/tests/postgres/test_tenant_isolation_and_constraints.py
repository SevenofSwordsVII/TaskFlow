"""Stage C: Tenant isolation, application authorization, and database relational integrity."""

import uuid

import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.base import utc_now
from app.core.dependencies import (
    get_accessible_board,
    get_accessible_list,
    get_accessible_project,
    get_accessible_task,
)
from app.core.exceptions import NotFoundException
from app.core.security import hash_password
from app.modules.kanban.models import Board, List, Task, TaskPriority
from app.modules.organizations.models import Organization, OrganizationMember, OrganizationRole
from app.modules.projects.models import Project, ProjectMember, ProjectRole, ProjectVisibility
from app.modules.users.models import User


async def _create_tenant_fixture(
    db: AsyncSession,
    slug: str,
    user_email: str,
) -> tuple[User, Organization, Project, Board, List, Task]:
    """Helper to provision a complete isolated tenant hierarchy with real database persistence."""
    user = User(
        id=uuid.uuid4(),
        email=user_email,
        full_name=f"User {slug}",
        hashed_password=hash_password("Password123!"),
        is_active=True,
    )
    org = Organization(
        id=uuid.uuid4(),
        name=f"Org {slug}",
        slug=slug,
        created_at=utc_now(),
        updated_at=utc_now(),
    )
    db.add_all([user, org])
    await db.flush()

    member = OrganizationMember(
        id=uuid.uuid4(),
        organization_id=org.id,
        user_id=user.id,
        role=OrganizationRole.OWNER,
        created_at=utc_now(),
        updated_at=utc_now(),
    )
    project = Project(
        id=uuid.uuid4(),
        organization_id=org.id,
        name=f"Project {slug}",
        key=f"P_{slug.upper()[:4]}",
        visibility=ProjectVisibility.RESTRICTED,
        created_by_id=user.id,
        created_at=utc_now(),
        updated_at=utc_now(),
    )
    db.add_all([member, project])
    await db.flush()

    pm = ProjectMember(
        id=uuid.uuid4(),
        project_id=project.id,
        user_id=user.id,
        project_role=ProjectRole.PROJECT_ADMIN,
        created_at=utc_now(),
    )
    board = Board(
        id=uuid.uuid4(),
        project_id=project.id,
        organization_id=org.id,
        name=f"Board {slug}",
        created_by_id=user.id,
        created_at=utc_now(),
        updated_at=utc_now(),
    )
    db.add_all([pm, board])
    await db.flush()

    lst = List(
        id=uuid.uuid4(),
        board_id=board.id,
        project_id=project.id,
        organization_id=org.id,
        name="Todo",
        ordering_key="1000",
        version=1,
        created_at=utc_now(),
        updated_at=utc_now(),
    )
    db.add(lst)
    await db.flush()

    task = Task(
        id=uuid.uuid4(),
        list_id=lst.id,
        board_id=board.id,
        project_id=project.id,
        organization_id=org.id,
        title="Initial Task",
        priority=TaskPriority.MEDIUM,
        ordering_key="1000",
        version=1,
        assignee_id=user.id,
        created_by_id=user.id,
        created_at=utc_now(),
        updated_at=utc_now(),
    )
    db.add(task)
    await db.commit()

    return user, org, project, board, lst, task


@pytest.mark.asyncio
async def test_cross_tenant_access_concealed_with_404(db_session: AsyncSession) -> None:
    """Verify application-level authorization conceals cross-tenant resources with 404."""
    user_a, org_a, prj_a, board_a, list_a, task_a = await _create_tenant_fixture(
        db_session, "tenant-a", "user_a@tenant-a.com"
    )
    user_b, org_b, prj_b, board_b, list_b, task_b = await _create_tenant_fixture(
        db_session, "tenant-b", "user_b@tenant-b.com"
    )

    # User B attempting to access Tenant A's project
    with pytest.raises(NotFoundException) as exc_info:
        await get_accessible_project(prj_a.id, user_b, db_session)
    assert exc_info.value.code == "PROJECT_NOT_FOUND"

    # User B attempting to access Tenant A's board
    with pytest.raises(NotFoundException) as exc_info:
        await get_accessible_board(board_a.id, user_b, db_session)
    assert exc_info.value.code == "BOARD_NOT_FOUND"

    # User B attempting to access Tenant A's list
    with pytest.raises(NotFoundException) as exc_info:
        await get_accessible_list(list_a.id, user_b, db_session)
    assert exc_info.value.code == "LIST_NOT_FOUND"

    # User B attempting to access Tenant A's task
    with pytest.raises(NotFoundException) as exc_info:
        await get_accessible_task(task_a.id, user_b, db_session)
    assert exc_info.value.code == "TASK_NOT_FOUND"


@pytest.mark.asyncio
async def test_database_cascade_delete_organization(db_session: AsyncSession) -> None:
    """Verify deleting organization cascades to projects, boards, lists, and tasks in PostgreSQL."""
    user, org, prj, board, lst, task = await _create_tenant_fixture(
        db_session, "cascade-org", "user_cascade@taskflow.dev"
    )
    org_id = org.id
    prj_id = prj.id
    board_id = board.id
    list_id = lst.id
    task_id = task.id

    # Execute hard delete on organization in real PostgreSQL
    await db_session.execute(delete(Organization).where(Organization.id == org_id))
    await db_session.commit()

    # Verify dependent rows are deleted by PostgreSQL FK cascade constraints
    assert (
        await db_session.execute(select(Project).where(Project.id == prj_id))
    ).scalar_one_or_none() is None
    assert (
        await db_session.execute(select(Board).where(Board.id == board_id))
    ).scalar_one_or_none() is None
    assert (
        await db_session.execute(select(List).where(List.id == list_id))
    ).scalar_one_or_none() is None
    assert (
        await db_session.execute(select(Task).where(Task.id == task_id))
    ).scalar_one_or_none() is None


@pytest.mark.asyncio
async def test_database_task_assignee_set_null_on_user_delete(db_session: AsyncSession) -> None:
    """Verify deleting user sets task assignee_id to NULL rather than deleting task."""
    _user, _org, _prj, _board, _lst, task = await _create_tenant_fixture(
        db_session, "assignee-null", "user_assigned@taskflow.dev"
    )
    task_id = task.id

    # Note: user is also created_by_id on board/task (which is NO ACTION / RESTRICT).
    # To test assignee_id SET NULL cascade, assign task to a separate assignee user.
    assignee = User(
        id=uuid.uuid4(),
        email="only_assignee@taskflow.dev",
        full_name="Assignee",
        hashed_password="pw",
        is_active=True,
    )
    db_session.add(assignee)
    await db_session.flush()

    # Update task assignee
    task.assignee_id = assignee.id
    await db_session.commit()

    # Delete assignee user in PostgreSQL
    await db_session.execute(delete(User).where(User.id == assignee.id))
    await db_session.commit()
    db_session.expire_all()

    # Verify task still exists and assignee_id is now NULL in PostgreSQL
    refreshed_task = (
        await db_session.execute(select(Task).where(Task.id == task_id))
    ).scalar_one_or_none()
    assert refreshed_task is not None
    assert refreshed_task.assignee_id is None
