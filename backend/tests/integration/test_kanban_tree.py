"""Integration tests for eager board tree hierarchy loading via selectinload and soft-delete exclusion."""

import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock

from app.core.exceptions import NotFoundException
from app.modules.kanban.models import Board, List, Task
from app.modules.kanban.service import KanbanService
from tests.utils import run_async


def test_board_tree_not_found_raises_404() -> None:
    """Non-existent board must raise 404 BOARD_NOT_FOUND."""
    db = AsyncMock()
    db.execute.return_value = MagicMock(scalar_one_or_none=MagicMock(return_value=None))

    service = KanbanService(db)
    try:
        run_async(service.get_board_tree(uuid.uuid4()))
        assert False, "Expected NotFoundException"
    except NotFoundException as exc:
        assert exc.code == "BOARD_NOT_FOUND"


def test_board_tree_eager_loading_and_sorting() -> None:
    """Board hierarchy must return lists and tasks ordered deterministically by ordering_key."""
    board_id = uuid.uuid4()
    board = MagicMock(spec=Board)
    board.id = board_id
    board.project_id = uuid.uuid4()
    board.name = "Sprint Board"
    board.description = "Main board"
    board.created_at = "2026-10-11T00:00:00Z"
    board.updated_at = "2026-10-11T00:00:00Z"

    list_b = MagicMock(spec=List)
    list_b.id = uuid.uuid4()
    list_b.board_id = board_id
    list_b.name = "Done"
    list_b.ordering_key = "0|r"
    list_b.version = 1
    list_b.deleted_at = None
    list_b.tasks = []

    list_a = MagicMock(spec=List)
    list_a.id = uuid.uuid4()
    list_a.board_id = board_id
    list_a.name = "Todo"
    list_a.ordering_key = "0|i"
    list_a.version = 1
    list_a.deleted_at = None

    task_2 = MagicMock(spec=Task)
    task_2.id = uuid.uuid4()
    task_2.list_id = list_a.id
    task_2.title = "Task 2"
    task_2.description = None
    task_2.ordering_key = "0|r"
    task_2.version = 1
    task_2.priority = "MEDIUM"
    task_2.assignee_id = None
    task_2.due_date = None
    task_2.deleted_at = None
    task_2.created_at = "2026-10-11T00:00:00Z"
    task_2.updated_at = "2026-10-11T00:00:00Z"

    task_1 = MagicMock(spec=Task)
    task_1.id = uuid.uuid4()
    task_1.list_id = list_a.id
    task_1.title = "Task 1"
    task_1.description = None
    task_1.ordering_key = "0|i"
    task_1.version = 1
    task_1.priority = "HIGH"
    task_1.assignee_id = None
    task_1.due_date = None
    task_1.deleted_at = None
    task_1.created_at = "2026-10-11T00:00:00Z"
    task_1.updated_at = "2026-10-11T00:00:00Z"

    # Tasks on list_a in arbitrary order; service sorts by ordering_key
    list_a.tasks = [task_2, task_1]
    # Lists on board in arbitrary order; service sorts by ordering_key
    board.lists = [list_b, list_a]

    db = AsyncMock()
    db.execute.return_value = MagicMock(scalar_one_or_none=MagicMock(return_value=board))

    service = KanbanService(db)
    tree = run_async(service.get_board_tree(board_id))

    assert tree.id == board_id
    # Lists sorted by ordering_key: "0|i" before "0|r"
    assert tree.lists[0].id == list_a.id
    assert tree.lists[1].id == list_b.id

    # Tasks sorted by ordering_key: "0|i" before "0|r"
    assert tree.lists[0].tasks[0].id == task_1.id
    assert tree.lists[0].tasks[1].id == task_2.id


def test_list_project_boards_existing() -> None:
    """When project already has boards, list_project_boards returns them without creating duplicates."""
    from app.modules.projects.models import Project

    project = MagicMock(spec=Project)
    project.id = uuid.uuid4()
    project.name = "My Project"
    project.organization_id = uuid.uuid4()
    project.created_by_id = uuid.uuid4()

    existing_board = MagicMock(spec=Board)
    existing_board.id = uuid.uuid4()
    existing_board.project_id = project.id
    existing_board.organization_id = project.organization_id
    existing_board.name = "Existing Board"
    existing_board.description = None
    existing_board.created_by_id = project.created_by_id
    existing_board.created_at = "2026-10-11T00:00:00Z"
    existing_board.updated_at = "2026-10-11T00:00:00Z"

    db = AsyncMock()
    db.execute.return_value = MagicMock(
        scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[existing_board])))
    )

    service = KanbanService(db)
    boards = run_async(service.list_project_boards(project))

    assert len(boards) == 1
    assert boards[0].id == existing_board.id
    assert boards[0].name == "Existing Board"
    # Ensure db.add was NOT called
    assert not db.add.called


def test_list_project_boards_auto_initializes_default_board() -> None:
    """When project has no boards, list_project_boards auto-creates a default board with workflow lists."""
    from app.modules.projects.models import Project

    project = MagicMock(spec=Project)
    project.id = uuid.uuid4()
    project.name = "Empty Project"
    project.organization_id = uuid.uuid4()
    project.created_by_id = uuid.uuid4()

    db = AsyncMock()
    # First query returns empty list
    db.execute.return_value = MagicMock(
        scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))
    )

    added_objects: list[Any] = []

    def mock_add(obj: Any) -> None:
        added_objects.append(obj)

    db.add = MagicMock(side_effect=mock_add)

    service = KanbanService(db)
    boards = run_async(service.list_project_boards(project))

    assert len(boards) == 1
    assert boards[0].name == "Empty Project Board"
    assert db.add.call_count == 4  # 1 Board + 3 Lists (To Do, In Progress, Done)
    board_obj = added_objects[0]
    assert isinstance(board_obj, Board)
    list_names = [item.name for item in added_objects[1:]]
    assert list_names == ["To Do", "In Progress", "Done"]


def test_get_boards_missing_project_id_raises_400() -> None:
    """Calling get_boards without project or project_id raises 400 PROJECT_ID_REQUIRED."""
    from app.core.exceptions import BadRequestException
    from app.modules.kanban.router import get_boards
    from app.modules.users.models import User

    db = AsyncMock()
    user = MagicMock(spec=User)
    try:
        run_async(get_boards(project=None, project_id=None, current_user=user, db=db))
        assert False, "Expected BadRequestException"
    except BadRequestException as exc:
        assert exc.code == "PROJECT_ID_REQUIRED"
        assert exc.status_code == 400


if __name__ == "__main__":
    test_board_tree_not_found_raises_404()
    test_board_tree_eager_loading_and_sorting()
    test_list_project_boards_existing()
    test_list_project_boards_auto_initializes_default_board()
    test_get_boards_missing_project_id_raises_400()
    print("All Kanban tree integration tests passed successfully!")
