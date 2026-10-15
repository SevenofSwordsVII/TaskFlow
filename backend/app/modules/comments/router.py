"""Comments API router handling task discussion threads."""

import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_active_user, get_db, require_task_access
from app.modules.comments.schemas import (
    CommentCreate,
    CommentListResponse,
    CommentRead,
    CommentUpdate,
)
from app.modules.comments.service import CommentService
from app.modules.kanban.models import Task
from app.modules.users.models import User

router = APIRouter(tags=["comments"])


@router.post(
    "/tasks/{task_id}/comments",
    status_code=status.HTTP_201_CREATED,
    response_model=CommentRead,
    summary="Add comment to task",
)
async def create_comment(
    task_id: uuid.UUID,
    payload: CommentCreate,
    task: Task = Depends(require_task_access("MEMBER")),
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> CommentRead:
    """Create a new comment on a task with project authorization enforcement."""
    _ = task
    service = CommentService(db)
    return await service.create_comment(task_id, payload, author=current_user)


@router.get(
    "/tasks/{task_id}/comments",
    response_model=CommentListResponse,
    summary="List comments on task",
)
async def list_comments(
    task_id: uuid.UUID,
    task: Task = Depends(require_task_access("VIEWER")),
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> CommentListResponse:
    """Retrieve comments for a task ordered chronologically."""
    _ = task
    service = CommentService(db)
    return await service.list_comments(task_id, user=current_user)


@router.patch(
    "/comments/{comment_id}",
    response_model=CommentRead,
    summary="Update comment content",
)
async def update_comment(
    comment_id: uuid.UUID,
    payload: CommentUpdate,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> CommentRead:
    """Update comment. Author-only editing strictly enforced."""
    service = CommentService(db)
    return await service.update_comment(comment_id, payload, user=current_user)


@router.delete(
    "/comments/{comment_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Soft-delete comment",
)
async def delete_comment(
    comment_id: uuid.UUID,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Soft-delete comment. Author or organization admin only."""
    service = CommentService(db)
    await service.delete_comment(comment_id, user=current_user)
