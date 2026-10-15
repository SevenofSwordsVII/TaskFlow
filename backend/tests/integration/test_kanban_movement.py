"""Integration tests for O(1) task movement, container row locks, OCC version checks, and rebalancing."""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.base import utc_now
from app.core.exceptions import BadRequestException, ConflictException
from app.modules.kanban.lexorank import rebalance_container
from app.modules.kanban.models import Board, List, Task
from app.modules.kanban.schemas import ListMoveRequest, TaskMoveRequest
from app.modules.kanban.service import KanbanService
from tests.utils import run_async


def test_occ_version_mismatch_raises_409() -> None:
    """When client presents stale expected_version, service must raise 409 TASK_VERSION_CONFLICT."""
    db = AsyncMock()
    task_id = uuid.uuid4()
    list_id = uuid.uuid4()
    board_id = uuid.uuid4()

    task = MagicMock(spec=Task)
    task.id = task_id
    task.list_id = list_id
    task.board_id = board_id
    task.version = 5  # Current DB version is 5

    target_list = MagicMock(spec=List)
    target_list.id = list_id
    target_list.board_id = board_id

    # Returns task, then target_list
    db.execute.return_value = MagicMock(
        scalar_one_or_none=MagicMock(side_effect=[task, target_list])
    )

    service = KanbanService(db)
    payload = TaskMoveRequest(
        target_list_id=list_id,
        expected_version=4,  # Stale version!
        prev_task_id=None,
        next_task_id=None,
    )

    with pytest.raises(ConflictException) as exc_info:
        run_async(service.move_task(task_id, payload))
    assert exc_info.value.code == "TASK_VERSION_CONFLICT"
    assert exc_info.value.details["current_version"] == 5


def test_cross_board_movement_rejected() -> None:
    """Moving task to list on a different board must be rejected with 400 INVALID_MOVE_BOUNDARY."""
    db = AsyncMock()
    task_id = uuid.uuid4()
    list_id_a = uuid.uuid4()
    list_id_b = uuid.uuid4()
    board_id_a = uuid.uuid4()
    board_id_b = uuid.uuid4()

    task = MagicMock(spec=Task)
    task.id = task_id
    task.list_id = list_id_a
    task.board_id = board_id_a
    task.version = 1

    list_a = MagicMock(spec=List, id=list_id_a, board_id=board_id_a)
    target_list = MagicMock(spec=List, id=list_id_b, board_id=board_id_b)  # Different board!
    ordered_lists = [list_a, target_list] if list_id_a < list_id_b else [target_list, list_a]

    # Return task, then ordered lists
    db.execute.return_value = MagicMock(
        scalar_one_or_none=MagicMock(side_effect=[task, *ordered_lists])
    )

    service = KanbanService(db)
    payload = TaskMoveRequest(
        target_list_id=list_id_b,
        expected_version=1,
        prev_task_id=None,
        next_task_id=None,
    )

    with pytest.raises(BadRequestException) as exc_info:
        run_async(service.move_task(task_id, payload))
    assert exc_info.value.code == "INVALID_MOVE_BOUNDARY"


def test_self_neighbor_reference_rejected() -> None:
    """Referencing task itself as prev or next neighbor must raise 400 SELF_NEIGHBOR_REJECTED."""
    db = AsyncMock()
    task_id = uuid.uuid4()
    list_id = uuid.uuid4()
    board_id = uuid.uuid4()

    task = MagicMock(spec=Task)
    task.id = task_id
    task.list_id = list_id
    task.board_id = board_id
    task.version = 1

    target_list = MagicMock(spec=List)
    target_list.id = list_id
    target_list.board_id = board_id

    db.execute.return_value = MagicMock(
        scalar_one_or_none=MagicMock(side_effect=[task, target_list])
    )
    service = KanbanService(db)

    payload = TaskMoveRequest(
        target_list_id=list_id,
        expected_version=1,
        prev_task_id=task_id,  # Self neighbor!
        next_task_id=None,
    )

    with pytest.raises(BadRequestException) as exc_info:
        run_async(service.move_task(task_id, payload))
    assert exc_info.value.code == "SELF_NEIGHBOR_REJECTED"


def test_successful_o1_task_movement() -> None:
    """Successful move updates exactly one task row, increments version, and calculates LexoRank."""
    db = AsyncMock()
    task_id = uuid.uuid4()
    list_id = uuid.uuid4()
    board_id = uuid.uuid4()

    now = utc_now()
    task = MagicMock(spec=Task)
    task.id = task_id
    task.list_id = list_id
    task.board_id = board_id
    task.project_id = uuid.uuid4()
    task.organization_id = uuid.uuid4()
    task.title = "Task 1"
    task.description = None
    task.priority = "MEDIUM"
    task.version = 1
    task.ordering_key = "0|h"
    task.assignee_id = None
    task.due_date = None
    task.completed_at = None
    task.created_by_id = uuid.uuid4()
    task.created_at = now
    task.updated_at = now

    target_list = MagicMock(spec=List)
    target_list.id = list_id
    target_list.board_id = board_id

    # Queries:
    # 1. task lookup
    # 2. list lock
    # 3. tasks in target list (empty target list)
    exec_mock = MagicMock()
    exec_mock.scalar_one_or_none.side_effect = [task, target_list]
    exec_mock.scalars.return_value.all.return_value = []
    db.execute.return_value = exec_mock

    service = KanbanService(db)
    payload = TaskMoveRequest(
        target_list_id=list_id,
        expected_version=1,
        prev_task_id=None,
        next_task_id=None,
    )

    moved_task = run_async(service.move_task(task_id, payload))
    assert moved_task.version == 2
    assert task.version == 2
    assert task.ordering_key == "0|i"
    assert db.commit.called


def test_task_movement_rebalance_same_list() -> None:
    """When rebalancing triggers in same list, all tasks are reordered and assigned evenly spaced keys."""
    db = AsyncMock()
    list_id = uuid.uuid4()
    board_id = uuid.uuid4()
    org_id = uuid.uuid4()
    proj_id = uuid.uuid4()

    now = utc_now()

    def make_task(
        tid: uuid.UUID,
        title: str,
        key: str,
        version: int = 1,
    ) -> MagicMock:
        t = MagicMock(spec=Task)
        t.id = tid
        t.list_id = list_id
        t.board_id = board_id
        t.project_id = proj_id
        t.organization_id = org_id
        t.title = title
        t.description = None
        t.priority = "MEDIUM"
        t.version = version
        t.ordering_key = key
        t.assignee_id = None
        t.due_date = None
        t.completed_at = None
        t.created_by_id = uuid.uuid4()
        t.created_at = now
        t.updated_at = now
        return t

    t1_id = uuid.uuid4()
    t2_id = uuid.uuid4()
    t3_id = uuid.uuid4()

    t1 = make_task(t1_id, "Task 1", "0|1")
    t2 = make_task(t2_id, "Task 2", "0|9")
    t3 = make_task(t3_id, "Task 3", "0|z")

    target_list = MagicMock(spec=List, id=list_id, board_id=board_id)

    # s_target returns [t1, t2] (excluding moved t3)
    exec_mock = MagicMock()
    exec_mock.scalar_one_or_none.side_effect = [t3, target_list]
    exec_mock.scalars.return_value.all.return_value = [t1, t2]
    db.execute.return_value = exec_mock

    service = KanbanService(db)
    # Move t3 between t1 and t2
    payload = TaskMoveRequest(
        target_list_id=list_id,
        expected_version=1,
        prev_task_id=t1_id,
        next_task_id=t2_id,
    )

    with patch("app.modules.kanban.service.needs_rebalance", return_value=True):
        moved_t3 = run_async(service.move_task(t3_id, payload))

    # All three tasks must have received newly rebalanced keys in the order [t1, t3, t2]
    assert t3.version == 2
    assert moved_t3.version == 2
    assert t1.ordering_key < t3.ordering_key < t2.ordering_key
    expected_keys = rebalance_container(3)
    assert t1.ordering_key == expected_keys[0]
    assert t3.ordering_key == expected_keys[1]
    assert t2.ordering_key == expected_keys[2]
    assert db.commit.called


def test_task_movement_rebalance_cross_list() -> None:
    """When rebalancing triggers in cross-list move, target container receives task in correct position."""
    db = AsyncMock()
    list_a_id = uuid.uuid4()
    list_b_id = uuid.uuid4()
    board_id = uuid.uuid4()
    org_id = uuid.uuid4()
    proj_id = uuid.uuid4()
    now = utc_now()

    def make_task(
        tid: uuid.UUID,
        lid: uuid.UUID,
        title: str,
        key: str,
        version: int = 1,
    ) -> MagicMock:
        t = MagicMock(spec=Task)
        t.id = tid
        t.list_id = lid
        t.board_id = board_id
        t.project_id = proj_id
        t.organization_id = org_id
        t.title = title
        t.description = None
        t.priority = "MEDIUM"
        t.version = version
        t.ordering_key = key
        t.assignee_id = None
        t.due_date = None
        t.completed_at = None
        t.created_by_id = uuid.uuid4()
        t.created_at = now
        t.updated_at = now
        return t

    t_moved_id = uuid.uuid4()
    t_target1_id = uuid.uuid4()
    t_target2_id = uuid.uuid4()

    t_moved = make_task(t_moved_id, list_a_id, "Moved Task", "0|m")
    t_target1 = make_task(t_target1_id, list_b_id, "Target 1", "0|1")
    t_target2 = make_task(t_target2_id, list_b_id, "Target 2", "0|9")

    list_a = MagicMock(spec=List, id=list_a_id, board_id=board_id)
    list_b = MagicMock(spec=List, id=list_b_id, board_id=board_id)
    ordered_lists = [list_a, list_b] if list_a_id < list_b_id else [list_b, list_a]

    # Queries:
    # 1. task lookup
    # 2. list lock 1
    # 3. list lock 2
    # 4. tasks in list_b
    exec_mock = MagicMock()
    exec_mock.scalar_one_or_none.side_effect = [t_moved, *ordered_lists]
    exec_mock.scalars.return_value.all.return_value = [t_target1, t_target2]
    db.execute.return_value = exec_mock

    service = KanbanService(db)
    # Move t_moved to list_b at the head (before t_target1)
    payload = TaskMoveRequest(
        target_list_id=list_b_id,
        expected_version=1,
        prev_task_id=None,
        next_task_id=t_target1_id,
    )

    with patch("app.modules.kanban.service.needs_rebalance", return_value=True):
        moved_res = run_async(service.move_task(t_moved_id, payload))

    assert t_moved.list_id == list_b_id
    assert t_moved.version == 2
    assert moved_res.list_id == list_b_id
    # Order must be [t_moved, t_target1, t_target2]
    assert t_moved.ordering_key < t_target1.ordering_key < t_target2.ordering_key
    expected_keys = rebalance_container(3)
    assert t_moved.ordering_key == expected_keys[0]
    assert t_target1.ordering_key == expected_keys[1]
    assert t_target2.ordering_key == expected_keys[2]
    assert db.commit.called


def test_list_movement_rebalance() -> None:
    """When rebalancing triggers for lists on a board, all lists are rebalanced in new order."""
    db = AsyncMock()
    board_id = uuid.uuid4()
    org_id = uuid.uuid4()
    proj_id = uuid.uuid4()
    now = utc_now()

    def make_list(
        lid: uuid.UUID,
        name: str,
        key: str,
        version: int = 1,
    ) -> MagicMock:
        lst = MagicMock(spec=List)
        lst.id = lid
        lst.board_id = board_id
        lst.project_id = proj_id
        lst.organization_id = org_id
        lst.name = name
        lst.ordering_key = key
        lst.version = version
        lst.created_at = now
        lst.updated_at = now
        return lst

    l1_id = uuid.uuid4()
    l2_id = uuid.uuid4()
    l3_id = uuid.uuid4()

    l1 = make_list(l1_id, "List 1", "0|1")
    l2 = make_list(l2_id, "List 2", "0|5")
    l3 = make_list(l3_id, "List 3", "0|9")

    board = MagicMock(spec=Board, id=board_id)

    # 1. target list lookup (l1)
    # 2. board lock
    # 3. s_board query -> [l2, l3]
    exec_mock = MagicMock()
    exec_mock.scalar_one_or_none.side_effect = [l1, board]
    exec_mock.scalars.return_value.all.return_value = [l2, l3]
    db.execute.return_value = exec_mock

    service = KanbanService(db)
    # Move l1 to the end after l3
    payload = ListMoveRequest(
        prev_list_id=l3_id,
        next_list_id=None,
        expected_version=1,
    )

    with patch("app.modules.kanban.service.needs_rebalance", return_value=True):
        moved_l1 = run_async(service.move_list(l1_id, payload))

    assert l1.version == 2
    assert moved_l1.version == 2
    # Order must be [l2, l3, l1]
    assert l2.ordering_key < l3.ordering_key < l1.ordering_key
    expected_keys = rebalance_container(3)
    assert l2.ordering_key == expected_keys[0]
    assert l3.ordering_key == expected_keys[1]
    assert l1.ordering_key == expected_keys[2]
    assert db.commit.called


def test_list_occ_version_mismatch_raises_409() -> None:
    """When moving list with stale version, 409 LIST_VERSION_CONFLICT is raised."""
    db = AsyncMock()
    list_id = uuid.uuid4()
    board_id = uuid.uuid4()

    lst = MagicMock(spec=List, id=list_id, board_id=board_id, version=3)
    board = MagicMock(spec=Board, id=board_id)

    exec_mock = MagicMock()
    exec_mock.scalar_one_or_none.side_effect = [lst, board]
    db.execute.return_value = exec_mock

    service = KanbanService(db)
    payload = ListMoveRequest(
        prev_list_id=None,
        next_list_id=None,
        expected_version=2,  # Stale
    )

    with pytest.raises(ConflictException) as exc_info:
        run_async(service.move_list(list_id, payload))
    assert exc_info.value.code == "LIST_VERSION_CONFLICT"
    assert exc_info.value.details["current_version"] == 3


if __name__ == "__main__":
    test_occ_version_mismatch_raises_409()
    test_cross_board_movement_rejected()
    test_self_neighbor_reference_rejected()
    test_successful_o1_task_movement()
    test_task_movement_rebalance_same_list()
    test_task_movement_rebalance_cross_list()
    test_list_movement_rebalance()
    test_list_occ_version_mismatch_raises_409()
    print("All Kanban movement & rebalance integration tests passed successfully!")
