"""Kanban domain service managing Boards, Lists, Tasks, and O(1) OCC movement."""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.base import utc_now
from app.core.dependencies import (
    get_accessible_board,
    get_accessible_list,
    get_accessible_project,
    get_accessible_task,
)
from app.core.exceptions import (
    BadRequestException,
    ConflictException,
    NotFoundException,
)
from app.modules.kanban.lexorank import (
    between_keys,
    needs_rebalance,
    rebalance_container,
)
from app.modules.kanban.models import Board, List, Task
from app.modules.kanban.schemas import (
    BoardCreate,
    BoardRead,
    BoardTreeRead,
    ListCreate,
    ListMoveRequest,
    ListRead,
    ListTreeRead,
    TaskBriefRead,
    TaskCreate,
    TaskMoveRequest,
    TaskRead,
    TaskUpdate,
)
from app.modules.projects.models import Project
from app.modules.users.models import User


class KanbanService:
    """Service encapsulating Kanban operations with container row locking and OCC."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def create_board(
        self,
        project_id: uuid.UUID,
        payload: BoardCreate,
        creator: User,
    ) -> BoardRead:
        """Create a new Kanban board inside a project."""
        project = await get_accessible_project(project_id, creator, self.db, min_role="MEMBER")

        board = Board(
            id=uuid.uuid4(),
            project_id=project.id,
            organization_id=project.organization_id,
            name=payload.name.strip(),
            description=payload.description.strip() if payload.description else None,
            created_by_id=creator.id,
        )
        self.db.add(board)
        await self.db.commit()
        await self.db.refresh(board)

        return BoardRead.model_validate(board)

    async def list_project_boards(
        self,
        project: Project,
        creator: User | None = None,
    ) -> list[BoardRead]:
        """List active boards for a project. Auto-initializes default board if none exist."""
        stmt = (
            select(Board)
            .where(
                Board.project_id == project.id,
                Board.deleted_at.is_(None),
            )
            .order_by(Board.created_at.asc())
        )
        boards = (await self.db.execute(stmt)).scalars().all()
        if boards:
            return [BoardRead.model_validate(b) for b in boards]

        creator_id = creator.id if creator else project.created_by_id
        now = utc_now()
        board = Board(
            id=uuid.uuid4(),
            project_id=project.id,
            organization_id=project.organization_id,
            name=f"{project.name} Board",
            description=f"Main board for {project.name}",
            created_by_id=creator_id,
            created_at=now,
            updated_at=now,
        )
        self.db.add(board)
        await self.db.flush()

        key_todo = between_keys(None, None)
        key_prog = between_keys(key_todo, None)
        key_done = between_keys(key_prog, None)

        for name, key in [("To Do", key_todo), ("In Progress", key_prog), ("Done", key_done)]:
            lst = List(
                id=uuid.uuid4(),
                board_id=board.id,
                project_id=project.id,
                organization_id=project.organization_id,
                name=name,
                ordering_key=key,
                version=1,
                created_at=now,
                updated_at=now,
            )
            self.db.add(lst)

        await self.db.commit()
        await self.db.refresh(board)
        return [BoardRead.model_validate(board)]

    async def get_board_tree(
        self,
        board_id: uuid.UUID,
        user: User | None = None,
    ) -> BoardTreeRead:
        """Eagerly load Board -> Lists -> Tasks hierarchy using selectinload."""
        if user is not None:
            await get_accessible_board(board_id, user, self.db, min_role="VIEWER")

        stmt = (
            select(Board)
            .where(
                Board.id == board_id,
                Board.deleted_at.is_(None),
            )
            .options(
                selectinload(Board.lists.and_(List.deleted_at.is_(None))).selectinload(
                    List.tasks.and_(Task.deleted_at.is_(None))
                )
            )
        )
        board = (await self.db.execute(stmt)).scalar_one_or_none()
        if not board:
            raise NotFoundException(
                code="BOARD_NOT_FOUND",
                message="Board does not exist or access denied.",
            )

        # Sort lists and tasks deterministically by ordering_key
        sorted_lists = sorted(board.lists, key=lambda lst_item: lst_item.ordering_key)
        tree_lists: list[ListTreeRead] = []

        for lst in sorted_lists:
            sorted_tasks = sorted(lst.tasks, key=lambda t: t.ordering_key)
            tree_lists.append(
                ListTreeRead(
                    id=lst.id,
                    name=lst.name,
                    ordering_key=lst.ordering_key,
                    version=lst.version,
                    tasks=[
                        TaskBriefRead(
                            id=t.id,
                            title=t.title,
                            priority=t.priority.value
                            if hasattr(t.priority, "value")
                            else str(t.priority),
                            version=t.version,
                            ordering_key=t.ordering_key,
                            assignee_id=t.assignee_id,
                            due_date=t.due_date,
                        )
                        for t in sorted_tasks
                    ],
                )
            )

        return BoardTreeRead(
            id=board.id,
            project_id=board.project_id,
            name=board.name,
            description=board.description,
            lists=tree_lists,
        )

    async def create_list(
        self,
        board_id: uuid.UUID,
        payload: ListCreate,
        creator: User,
    ) -> ListRead:
        """Create a new list on the board, acquiring board row lock and computing LexoRank key."""
        await get_accessible_board(board_id, creator, self.db, min_role="MEMBER")

        board_stmt = (
            select(Board)
            .where(
                Board.id == board_id,
                Board.deleted_at.is_(None),
            )
            .with_for_update()
        )
        board = (await self.db.execute(board_stmt)).scalar_one_or_none()
        if not board:
            raise NotFoundException("BOARD_NOT_FOUND", "Board not found or deleted.")

        lists_stmt = (
            select(List)
            .where(
                List.board_id == board_id,
                List.deleted_at.is_(None),
            )
            .order_by(List.ordering_key.asc())
        )
        active_lists = (await self.db.execute(lists_stmt)).scalars().all()

        if payload.prev_list_id:
            idx = next(
                (
                    i
                    for i, lst_item in enumerate(active_lists)
                    if lst_item.id == payload.prev_list_id
                ),
                None,
            )
            if idx is None:
                raise BadRequestException(
                    code="INVALID_NEIGHBOR_REFERENCE",
                    message="Referenced previous list does not exist on this board.",
                )
            prev_key = active_lists[idx].ordering_key
            next_key = active_lists[idx + 1].ordering_key if idx + 1 < len(active_lists) else None
            new_key = between_keys(prev_key, next_key)
        elif active_lists:
            new_key = between_keys(active_lists[-1].ordering_key, None)
        else:
            new_key = between_keys(None, None)

        new_list = List(
            id=uuid.uuid4(),
            board_id=board.id,
            project_id=board.project_id,
            organization_id=board.organization_id,
            name=payload.name.strip(),
            ordering_key=new_key,
            version=1,
        )
        self.db.add(new_list)
        await self.db.commit()
        await self.db.refresh(new_list)
        return ListRead.model_validate(new_list)

    async def move_list(
        self,
        list_id: uuid.UUID,
        payload: ListMoveRequest,
        user: User | None = None,
    ) -> ListRead:
        """Reorder list horizontally with board lock, OCC check, and neighbor validation."""
        if user is not None:
            await get_accessible_list(list_id, user, self.db, min_role="MEMBER")

        target_stmt = select(List).where(
            List.id == list_id,
            List.deleted_at.is_(None),
        )
        target_list = (await self.db.execute(target_stmt)).scalar_one_or_none()
        if not target_list:
            raise NotFoundException("LIST_NOT_FOUND", "List not found or deleted.")

        # Acquire row lock on parent board
        board_stmt = (
            select(Board)
            .where(
                Board.id == target_list.board_id,
                Board.deleted_at.is_(None),
            )
            .with_for_update()
        )
        await self.db.execute(board_stmt)
        await self.db.refresh(target_list)

        # OCC Version check
        if target_list.version != payload.expected_version:
            raise ConflictException(
                code="LIST_VERSION_CONFLICT",
                message="List was modified concurrently by another user.",
                details={"current_version": target_list.version},
            )

        if payload.prev_list_id == list_id or payload.next_list_id == list_id:
            raise BadRequestException(
                code="SELF_NEIGHBOR_REJECTED",
                message="List cannot be positioned relative to itself.",
            )

        # Hypothetical sequence of remaining lists excluding moved list
        s_stmt = (
            select(List)
            .where(
                List.board_id == target_list.board_id,
                List.deleted_at.is_(None),
                List.id != list_id,
            )
            .order_by(List.ordering_key.asc())
        )
        s_board = (await self.db.execute(s_stmt)).scalars().all()

        # Validate neighbor positions
        if payload.prev_list_id is None and payload.next_list_id is None:
            if s_board:
                raise BadRequestException(
                    code="INVALID_NEIGHBOR_REFERENCE",
                    message="Both neighbors cannot be null when other lists exist on the board.",
                )
            new_key = between_keys(None, None)
        elif payload.prev_list_id is None and payload.next_list_id is not None:
            if not s_board or s_board[0].id != payload.next_list_id:
                raise BadRequestException(
                    code="INVALID_NEIGHBOR_REFERENCE",
                    message="Next list must be the first list in the board sequence.",
                )
            new_key = between_keys(None, s_board[0].ordering_key)
        elif payload.prev_list_id is not None and payload.next_list_id is None:
            if not s_board or s_board[-1].id != payload.prev_list_id:
                raise BadRequestException(
                    code="INVALID_NEIGHBOR_REFERENCE",
                    message="Previous list must be the last list in the board sequence.",
                )
            new_key = between_keys(s_board[-1].ordering_key, None)
        else:
            prev_idx = next(
                (i for i, lst_item in enumerate(s_board) if lst_item.id == payload.prev_list_id),
                None,
            )
            next_idx = next(
                (i for i, lst_item in enumerate(s_board) if lst_item.id == payload.next_list_id),
                None,
            )
            if prev_idx is None or next_idx is None or next_idx != prev_idx + 1:
                raise BadRequestException(
                    code="INVALID_NEIGHBOR_REFERENCE",
                    message="Neighboring lists are not adjacent or do not belong to this board.",
                )
            new_key = between_keys(s_board[prev_idx].ordering_key, s_board[next_idx].ordering_key)

        # Check for legitimate no-op
        if target_list.ordering_key == new_key:
            return ListRead.model_validate(target_list)

        # Build complete ordered sequence for board
        if payload.prev_list_id is None and payload.next_list_id is None:
            new_order = [target_list]
        elif payload.prev_list_id is None:
            new_order = [target_list] + list(s_board)
        elif payload.next_list_id is None:
            new_order = list(s_board) + [target_list]
        else:
            new_order = list(s_board[:next_idx]) + [target_list] + list(s_board[next_idx:])

        # Rebalance check
        if needs_rebalance(new_key):
            rebalanced = rebalance_container(len(new_order))
            for i, lst_item in enumerate(new_order):
                lst_item.ordering_key = rebalanced[i]
        else:
            target_list.ordering_key = new_key

        target_list.version += 1
        await self.db.commit()
        await self.db.refresh(target_list)
        return ListRead.model_validate(target_list)

    async def create_task(
        self,
        list_id: uuid.UUID,
        payload: TaskCreate,
        creator: User,
    ) -> TaskRead:
        """Create a new task in a list with container row locking."""
        await get_accessible_list(list_id, creator, self.db, min_role="MEMBER")

        list_stmt = (
            select(List)
            .where(
                List.id == list_id,
                List.deleted_at.is_(None),
            )
            .with_for_update()
        )
        lst = (await self.db.execute(list_stmt)).scalar_one_or_none()
        if not lst:
            raise NotFoundException("LIST_NOT_FOUND", "List not found or deleted.")

        tasks_stmt = (
            select(Task)
            .where(
                Task.list_id == list_id,
                Task.deleted_at.is_(None),
            )
            .order_by(Task.ordering_key.asc())
        )
        active_tasks = (await self.db.execute(tasks_stmt)).scalars().all()

        if payload.prev_task_id:
            idx = next(
                (i for i, t in enumerate(active_tasks) if t.id == payload.prev_task_id), None
            )
            if idx is None:
                raise BadRequestException(
                    code="INVALID_NEIGHBOR_REFERENCE",
                    message="Referenced previous task does not exist in this list.",
                )
            prev_key = active_tasks[idx].ordering_key
            next_key = active_tasks[idx + 1].ordering_key if idx + 1 < len(active_tasks) else None
            new_key = between_keys(prev_key, next_key)
        elif active_tasks:
            new_key = between_keys(active_tasks[-1].ordering_key, None)
        else:
            new_key = between_keys(None, None)

        task = Task(
            id=uuid.uuid4(),
            list_id=lst.id,
            board_id=lst.board_id,
            project_id=lst.project_id,
            organization_id=lst.organization_id,
            title=payload.title.strip(),
            description=payload.description.strip() if payload.description else None,
            priority=payload.priority,
            ordering_key=new_key,
            version=1,
            assignee_id=payload.assignee_id,
            due_date=payload.due_date,
            created_by_id=creator.id,
        )
        self.db.add(task)
        await self.db.commit()
        await self.db.refresh(task)
        return TaskRead.model_validate(task)

    async def update_task(
        self,
        task_id: uuid.UUID,
        payload: TaskUpdate,
        user: User | None = None,
    ) -> TaskRead:
        """Update task title, description, priority, or due_date with OCC version check."""
        if user is not None:
            await get_accessible_task(task_id, user, self.db, min_role="MEMBER")

        stmt = (
            select(Task)
            .where(
                Task.id == task_id,
                Task.deleted_at.is_(None),
            )
            .with_for_update()
        )
        task = (await self.db.execute(stmt)).scalar_one_or_none()
        if not task:
            raise NotFoundException("TASK_NOT_FOUND", "Task not found or deleted.")

        if task.version != payload.expected_version:
            raise ConflictException(
                code="TASK_VERSION_CONFLICT",
                message="Task was modified concurrently by another user.",
                details={"current_version": task.version},
            )

        if payload.title is not None:
            task.title = payload.title.strip()
        if payload.description is not None:
            task.description = payload.description.strip() if payload.description else None
        if payload.priority is not None:
            task.priority = payload.priority
        if payload.assignee_id is not None:
            task.assignee_id = payload.assignee_id
        if payload.due_date is not None:
            task.due_date = payload.due_date

        task.version += 1
        await self.db.commit()
        await self.db.refresh(task)
        return TaskRead.model_validate(task)

    async def move_task(
        self,
        task_id: uuid.UUID,
        payload: TaskMoveRequest,
        user: User | None = None,
    ) -> TaskRead:
        """Execute O(1) single-row task move with container row locks and OCC."""
        if user is not None:
            await get_accessible_task(task_id, user, self.db, min_role="MEMBER")
            await get_accessible_list(payload.target_list_id, user, self.db, min_role="MEMBER")

        task_stmt = select(Task).where(
            Task.id == task_id,
            Task.deleted_at.is_(None),
        )
        task = (await self.db.execute(task_stmt)).scalar_one_or_none()
        if not task:
            raise NotFoundException("TASK_NOT_FOUND", "Task not found or deleted.")

        # Acquire container row locks in deterministic order
        is_same_list = task.list_id == payload.target_list_id
        if is_same_list:
            list_stmt = (
                select(List)
                .where(
                    List.id == payload.target_list_id,
                    List.deleted_at.is_(None),
                )
                .with_for_update()
            )
            target_list = (await self.db.execute(list_stmt)).scalar_one_or_none()
        else:
            ordered_ids = sorted([task.list_id, payload.target_list_id])
            for lid in ordered_ids:
                l_stmt = (
                    select(List)
                    .where(
                        List.id == lid,
                        List.deleted_at.is_(None),
                    )
                    .with_for_update()
                )
                res = (await self.db.execute(l_stmt)).scalar_one_or_none()
                if lid == payload.target_list_id:
                    target_list = res

        if not target_list:
            raise NotFoundException("TARGET_LIST_NOT_FOUND", "Target list not found or deleted.")

        # Refresh task state under container locks to ensure latest version is evaluated
        await self.db.refresh(task)

        # Cross-board movement rejected
        if target_list.board_id != task.board_id:
            raise BadRequestException(
                code="INVALID_MOVE_BOUNDARY",
                message="Cannot move task to a list on a different board.",
            )

        # OCC Version check
        if task.version != payload.expected_version:
            raise ConflictException(
                code="TASK_VERSION_CONFLICT",
                message="Task was modified concurrently by another user.",
                details={"current_version": task.version},
            )

        if payload.prev_task_id == task_id or payload.next_task_id == task_id:
            raise BadRequestException(
                code="SELF_NEIGHBOR_REJECTED",
                message="Task cannot be positioned relative to itself.",
            )

        # Hypothetical sequence in target list
        if is_same_list:
            t_stmt = (
                select(Task)
                .where(
                    Task.list_id == payload.target_list_id,
                    Task.deleted_at.is_(None),
                    Task.id != task_id,
                )
                .order_by(Task.ordering_key.asc())
            )
        else:
            t_stmt = (
                select(Task)
                .where(
                    Task.list_id == payload.target_list_id,
                    Task.deleted_at.is_(None),
                )
                .order_by(Task.ordering_key.asc())
            )
        s_target = (await self.db.execute(t_stmt)).scalars().all()

        # Validate neighbor positions
        if payload.prev_task_id is None and payload.next_task_id is None:
            if s_target:
                raise BadRequestException(
                    code="INVALID_NEIGHBOR_REFERENCE",
                    message="Both neighbors cannot be null when other tasks exist in target list.",
                )
            new_key = between_keys(None, None)
        elif payload.prev_task_id is None and payload.next_task_id is not None:
            if not s_target or s_target[0].id != payload.next_task_id:
                raise BadRequestException(
                    code="INVALID_NEIGHBOR_REFERENCE",
                    message="Next task must be the first task in target list.",
                )
            new_key = between_keys(None, s_target[0].ordering_key)
        elif payload.prev_task_id is not None and payload.next_task_id is None:
            if not s_target or s_target[-1].id != payload.prev_task_id:
                raise BadRequestException(
                    code="INVALID_NEIGHBOR_REFERENCE",
                    message="Previous task must be the last task in target list.",
                )
            new_key = between_keys(s_target[-1].ordering_key, None)
        else:
            prev_idx = next(
                (i for i, t in enumerate(s_target) if t.id == payload.prev_task_id), None
            )
            next_idx = next(
                (i for i, t in enumerate(s_target) if t.id == payload.next_task_id), None
            )
            if prev_idx is None or next_idx is None or next_idx != prev_idx + 1:
                raise BadRequestException(
                    code="INVALID_NEIGHBOR_REFERENCE",
                    message=(
                        "Neighboring tasks are not adjacent or do not belong to the target list."
                    ),
                )
            new_key = between_keys(s_target[prev_idx].ordering_key, s_target[next_idx].ordering_key)

        # Check for legitimate no-op (same list and key unchanged)
        if is_same_list and task.ordering_key == new_key:
            return TaskRead.model_validate(task)

        # Build complete ordered sequence for target container
        if payload.prev_task_id is None and payload.next_task_id is None:
            new_order = [task]
        elif payload.prev_task_id is None:
            new_order = [task] + list(s_target)
        elif payload.next_task_id is None:
            new_order = list(s_target) + [task]
        else:
            new_order = list(s_target[:next_idx]) + [task] + list(s_target[next_idx:])

        task.list_id = payload.target_list_id

        # Rebalance check
        if needs_rebalance(new_key):
            rebalanced = rebalance_container(len(new_order))
            for i, t in enumerate(new_order):
                t.ordering_key = rebalanced[i]
        else:
            task.ordering_key = new_key

        task.version += 1
        await self.db.commit()
        await self.db.refresh(task)
        return TaskRead.model_validate(task)

    async def delete_task(
        self,
        task_id: uuid.UUID,
        user: User | None = None,
    ) -> None:
        """Logically soft-delete a task."""
        if user is not None:
            await get_accessible_task(task_id, user, self.db, min_role="MEMBER")

        stmt = select(Task).where(
            Task.id == task_id,
            Task.deleted_at.is_(None),
        )
        task = (await self.db.execute(stmt)).scalar_one_or_none()
        if not task and user is not None:
            raise NotFoundException("TASK_NOT_FOUND", "Task not found or deleted.")
        if task:
            task.deleted_at = utc_now()
            await self.db.commit()
