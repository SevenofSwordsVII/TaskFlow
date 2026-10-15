"""Stage D: Kanban concurrency, OCC versioning, SELECT FOR UPDATE, and LexoRank ordering."""

import asyncio
import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.base import utc_now
from app.core.exceptions import ConflictException
from app.modules.kanban.lexorank import between_keys
from app.modules.kanban.models import Board, List, Task, TaskPriority
from app.modules.kanban.schemas import TaskMoveRequest, TaskUpdate
from app.modules.kanban.service import KanbanService
from app.modules.organizations.models import Organization, OrganizationMember, OrganizationRole
from app.modules.projects.models import Project, ProjectVisibility
from app.modules.users.models import User


async def _setup_kanban_fixture(
    db: AsyncSession,
) -> tuple[User, Organization, Project, Board, List, List, Task]:
    """Setup a standard Kanban board with two lists (L1, L2) and one task in L1."""
    user = User(
        id=uuid.uuid4(),
        email=f"kanban_{uuid.uuid4().hex[:6]}@taskflow.dev",
        full_name="Kanban User",
        hashed_password="pw",
        is_active=True,
    )
    org = Organization(
        id=uuid.uuid4(),
        name="Kanban Org",
        slug=f"k-org-{uuid.uuid4().hex[:6]}",
        created_at=utc_now(),
        updated_at=utc_now(),
    )
    db.add_all([user, org])
    await db.flush()

    org_member = OrganizationMember(
        id=uuid.uuid4(),
        organization_id=org.id,
        user_id=user.id,
        role=OrganizationRole.MEMBER,
        created_at=utc_now(),
        updated_at=utc_now(),
    )
    project = Project(
        id=uuid.uuid4(),
        organization_id=org.id,
        name="Kanban Project",
        key=f"K{uuid.uuid4().hex[:3].upper()}",
        visibility=ProjectVisibility.ORG_PUBLIC,
        created_by_id=user.id,
        created_at=utc_now(),
        updated_at=utc_now(),
    )
    db.add_all([org_member, project])
    await db.flush()

    board = Board(
        id=uuid.uuid4(),
        project_id=project.id,
        organization_id=org.id,
        name="Main Board",
        created_by_id=user.id,
        created_at=utc_now(),
        updated_at=utc_now(),
    )
    db.add(board)
    await db.flush()

    key_l1 = between_keys(None, None)
    key_l2 = between_keys(key_l1, None)
    l1 = List(
        id=uuid.uuid4(),
        board_id=board.id,
        project_id=project.id,
        organization_id=org.id,
        name="Backlog",
        ordering_key=key_l1,
        version=1,
        created_at=utc_now(),
        updated_at=utc_now(),
    )
    l2 = List(
        id=uuid.uuid4(),
        board_id=board.id,
        project_id=project.id,
        organization_id=org.id,
        name="Done",
        ordering_key=key_l2,
        version=1,
        created_at=utc_now(),
        updated_at=utc_now(),
    )
    db.add_all([l1, l2])
    await db.flush()

    task = Task(
        id=uuid.uuid4(),
        list_id=l1.id,
        board_id=board.id,
        project_id=project.id,
        organization_id=org.id,
        title="Initial Task",
        priority=TaskPriority.MEDIUM,
        ordering_key=between_keys(None, None),
        version=1,
        created_by_id=user.id,
        created_at=utc_now(),
        updated_at=utc_now(),
    )
    db.add(task)
    await db.commit()

    return user, org, project, board, l1, l2, task


@pytest.mark.asyncio
async def test_optimistic_concurrency_conflict_on_stale_task_version(
    db_session: AsyncSession,
) -> None:
    """Verify modifying a task with stale expected_version raises 409 Conflict."""
    _u, _o, _p, _b, _l1, _l2, task = await _setup_kanban_fixture(db_session)
    service = KanbanService(db_session)

    # First update: version 1 -> 2
    update_1 = TaskUpdate(
        title="Updated by Client 1",
        expected_version=1,
    )
    updated_task = await service.update_task(task.id, update_1)
    assert updated_task.version == 2
    assert updated_task.title == "Updated by Client 1"

    # Second update from stale Client 2 presenting expected_version=1
    update_2 = TaskUpdate(
        title="Updated by Stale Client 2",
        expected_version=1,
    )
    with pytest.raises(ConflictException) as exc_info:
        await service.update_task(task.id, update_2)

    assert exc_info.value.code == "TASK_VERSION_CONFLICT"
    assert exc_info.value.details == {"current_version": 2}


@pytest.mark.asyncio
async def test_concurrent_competing_task_moves(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Verify concurrent move operations on same task: one succeeds, one raises 409 Conflict."""
    async with session_factory() as setup_session:
        user, org, prj, board, l1, l2, task = await _setup_kanban_fixture(setup_session)
        task_id = task.id
        l2_id = l2.id

    barrier = asyncio.Barrier(2)

    async def _move_worker(worker_id: int) -> tuple[int, bool, str | None]:
        async with session_factory() as session:
            service = KanbanService(session)
            # Synchronize workers at barrier before initiating move
            await barrier.wait()
            try:
                payload = TaskMoveRequest(
                    target_list_id=l2_id,
                    prev_task_id=None,
                    next_task_id=None,
                    expected_version=1,
                )
                await service.move_task(task_id, payload)
                return worker_id, True, None
            except ConflictException as exc:
                return worker_id, False, exc.code

    results = await asyncio.gather(_move_worker(1), _move_worker(2))

    successes = [r for r in results if r[1] is True]
    conflicts = [r for r in results if r[1] is False]

    assert len(successes) == 1, f"Expected 1 success, got {len(successes)}"
    assert len(conflicts) == 1, f"Expected 1 conflict, got {len(conflicts)}"
    assert conflicts[0][2] == "TASK_VERSION_CONFLICT"

    # Verify final state in PostgreSQL: task is in L2 and has version 2
    async with session_factory() as verify_session:
        final_task = (
            await verify_session.execute(select(Task).where(Task.id == task_id))
        ).scalar_one()
        assert final_task.list_id == l2_id
        assert final_task.version == 2


@pytest.mark.asyncio
async def test_select_for_update_row_locking_behavior(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Verify PostgreSQL SELECT FOR UPDATE locks the list row against concurrent transactions."""
    async with session_factory() as setup_session:
        _, _, _, _, l1, _, _ = await _setup_kanban_fixture(setup_session)
        target_list_id = l1.id

    event_lock_acquired = asyncio.Event()
    event_release_lock = asyncio.Event()
    worker_2_acquired = asyncio.Event()

    async def _holder() -> None:
        async with session_factory() as session:
            # Begin explicit transaction and acquire row lock
            async with session.begin():
                await session.execute(
                    select(List).where(List.id == target_list_id).with_for_update()
                )
                event_lock_acquired.set()
                # Hold lock until release event
                await event_release_lock.wait()

    async def _waiter() -> None:
        await event_lock_acquired.wait()
        async with session_factory() as session:
            async with session.begin():
                # This must block while holder holds lock
                await session.execute(
                    select(List).where(List.id == target_list_id).with_for_update()
                )
                worker_2_acquired.set()

    holder_task = asyncio.create_task(_holder())
    waiter_task = asyncio.create_task(_waiter())

    await event_lock_acquired.wait()
    # Waiter should NOT acquire lock within 100ms because holder is holding it
    with pytest.raises(TimeoutError):
        await asyncio.wait_for(worker_2_acquired.wait(), timeout=0.1)

    assert not worker_2_acquired.is_set()

    # Now release holder's lock
    event_release_lock.set()
    await holder_task

    # Waiter must now immediately acquire lock
    await asyncio.wait_for(worker_2_acquired.wait(), timeout=2.0)
    assert worker_2_acquired.is_set()
    await waiter_task


@pytest.mark.asyncio
async def test_lexorank_ordering_persistence_in_postgres(
    db_session: AsyncSession,
) -> None:
    """Verify LexoRank ordering keys persist and sort correctly under PostgreSQL 'C' collation."""
    _u, _o, _p, _b, l1, _l2, task1 = await _setup_kanban_fixture(db_session)
    service = KanbanService(db_session)

    # Insert Task 2 after Task 1
    key_t2 = between_keys(task1.ordering_key, None)
    t2 = Task(
        id=uuid.uuid4(),
        list_id=l1.id,
        board_id=l1.board_id,
        project_id=l1.project_id,
        organization_id=l1.organization_id,
        title="Task 2",
        priority=TaskPriority.MEDIUM,
        ordering_key=key_t2,
        version=1,
        created_by_id=task1.created_by_id,
        created_at=utc_now(),
        updated_at=utc_now(),
    )
    db_session.add(t2)
    await db_session.commit()

    # Insert Task 3 after Task 2
    key_t3 = between_keys(key_t2, None)
    t3 = Task(
        id=uuid.uuid4(),
        list_id=l1.id,
        board_id=l1.board_id,
        project_id=l1.project_id,
        organization_id=l1.organization_id,
        title="Task 3 (In Between)",
        priority=TaskPriority.MEDIUM,
        ordering_key=key_t3,
        version=1,
        created_by_id=task1.created_by_id,
        created_at=utc_now(),
        updated_at=utc_now(),
    )
    db_session.add(t3)
    await db_session.commit()

    # Move t3 between task1 and t2
    payload = TaskMoveRequest(
        target_list_id=l1.id,
        prev_task_id=task1.id,
        next_task_id=t2.id,
        expected_version=1,
    )
    await service.move_task(t3.id, payload)

    # Query directly from PostgreSQL with ORDER BY ordering_key ASC
    stmt = (
        select(Task.title, Task.ordering_key)
        .where(Task.list_id == l1.id)
        .order_by(Task.ordering_key.asc())
    )
    rows = (await db_session.execute(stmt)).all()
    titles = [r[0] for r in rows]

    # Verify LexoRank correctly positioned Task 3 between Initial Task and Task 2
    assert titles == ["Initial Task", "Task 3 (In Between)", "Task 2"]
    assert rows[0][1] < rows[1][1] < rows[2][1]
