"""Kanban API router defining endpoints for Boards, Lists, Tasks, and OCC Moves."""

import uuid

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import (
    get_accessible_project,
    get_current_active_user,
    get_db,
    require_board_access,
    require_list_access,
    require_project_access,
    require_task_access,
)
from app.core.exceptions import BadRequestException
from app.modules.kanban.models import Board, List, Task
from app.modules.kanban.schemas import (
    BoardCreate,
    BoardRead,
    BoardTreeRead,
    ListCreate,
    ListMoveRequest,
    ListRead,
    TaskCreate,
    TaskMoveRequest,
    TaskRead,
    TaskUpdate,
)
from app.modules.kanban.service import KanbanService
from app.modules.projects.models import Project
from app.modules.users.models import User

router = APIRouter(tags=["kanban"])


@router.post(
    "/projects/{project_id}/boards",
    status_code=status.HTTP_201_CREATED,
    response_model=BoardRead,
    summary="Create Kanban board in project",
)
async def create_board(
    project_id: uuid.UUID,
    payload: BoardCreate,
    project: Project = Depends(require_project_access("MEMBER")),
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> BoardRead:
    """Create a new Kanban board inside the specified project."""
    _ = project
    service = KanbanService(db)
    return await service.create_board(project_id, payload, creator=current_user)


@router.get(
    "/projects/{project_id}/boards",
    response_model=list[BoardRead],
    summary="List Kanban boards in project",
)
async def list_project_boards(
    project_id: uuid.UUID,
    project: Project = Depends(require_project_access("VIEWER")),
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> list[BoardRead]:
    """Fetch all boards belonging to a project. If none exist, auto-initializes default board."""
    _ = project_id
    service = KanbanService(db)
    return await service.list_project_boards(project, creator=current_user)


@router.get(
    "/boards",
    response_model=list[BoardRead],
    summary="List Kanban boards with optional project filter",
)
async def get_boards(
    project: uuid.UUID | None = Query(default=None, description="Project ID query filter"),
    project_id: uuid.UUID | None = Query(default=None, description="Project ID query filter"),
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> list[BoardRead]:
    """Fetch boards matching query params. Conceals unauthorized projects with 404."""
    target_id = project or project_id
    if not target_id:
        raise BadRequestException(
            code="PROJECT_ID_REQUIRED",
            message="Query parameter 'project' or 'project_id' is required.",
        )
    project_obj = await get_accessible_project(target_id, current_user, db, min_role="VIEWER")
    service = KanbanService(db)
    return await service.list_project_boards(project_obj, creator=current_user)


@router.get(
    "/boards/{board_id}",
    response_model=BoardTreeRead,
    summary="Get eager Kanban board tree",
)
async def get_board(
    board_id: uuid.UUID,
    board: Board = Depends(require_board_access("VIEWER")),
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> BoardTreeRead:
    """Fetch complete Kanban board tree with eager loading (Board -> Lists -> Tasks)."""
    _ = board
    service = KanbanService(db)
    return await service.get_board_tree(board_id, user=current_user)


@router.post(
    "/boards/{board_id}/lists",
    status_code=status.HTTP_201_CREATED,
    response_model=ListRead,
    summary="Create list on board",
)
async def create_list(
    board_id: uuid.UUID,
    payload: ListCreate,
    board: Board = Depends(require_board_access("MEMBER")),
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> ListRead:
    """Add a new list column to the board with LexoRank positioning."""
    _ = board
    service = KanbanService(db)
    return await service.create_list(board_id, payload, creator=current_user)


@router.post(
    "/lists/{list_id}/move",
    response_model=ListRead,
    summary="Reorder list horizontally",
)
async def move_list(
    list_id: uuid.UUID,
    payload: ListMoveRequest,
    lst: List = Depends(require_list_access("MEMBER")),
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> ListRead:
    """Reorder list horizontally using neighboring IDs, OCC version check, and board row lock."""
    _ = lst
    service = KanbanService(db)
    return await service.move_list(list_id, payload, user=current_user)


@router.post(
    "/lists/{list_id}/tasks",
    status_code=status.HTTP_201_CREATED,
    response_model=TaskRead,
    summary="Create task in list",
)
async def create_task(
    list_id: uuid.UUID,
    payload: TaskCreate,
    lst: List = Depends(require_list_access("MEMBER")),
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> TaskRead:
    """Create a new task in a list with container row locking."""
    _ = lst
    service = KanbanService(db)
    return await service.create_task(list_id, payload, creator=current_user)


@router.patch(
    "/tasks/{task_id}",
    response_model=TaskRead,
    summary="Update task details",
)
async def update_task(
    task_id: uuid.UUID,
    payload: TaskUpdate,
    task: Task = Depends(require_task_access("MEMBER")),
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> TaskRead:
    """Update task fields with OCC version verification."""
    _ = task
    service = KanbanService(db)
    return await service.update_task(task_id, payload, user=current_user)


@router.post(
    "/tasks/{task_id}/move",
    response_model=TaskRead,
    summary="Move task with OCC",
)
async def move_task(
    task_id: uuid.UUID,
    payload: TaskMoveRequest,
    task: Task = Depends(require_task_access("MEMBER")),
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> TaskRead:
    """Execute O(1) single-row task move with container row locks and OCC version verification."""
    _ = task
    service = KanbanService(db)
    return await service.move_task(task_id, payload, user=current_user)


@router.delete(
    "/tasks/{task_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete task",
)
async def delete_task(
    task_id: uuid.UUID,
    task: Task = Depends(require_task_access("MEMBER")),
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Logically soft-delete a task."""
    _ = task
    service = KanbanService(db)
    await service.delete_task(task_id, user=current_user)
