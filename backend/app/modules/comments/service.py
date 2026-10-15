"""Comment domain service handling threaded task discussions."""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.base import utc_now
from app.core.dependencies import get_accessible_task
from app.core.exceptions import ForbiddenException, NotFoundException
from app.modules.comments.models import Comment
from app.modules.comments.schemas import (
    CommentCreate,
    CommentListResponse,
    CommentRead,
    CommentUpdate,
)
from app.modules.organizations.models import OrganizationMember, OrganizationRole
from app.modules.users.models import User
from app.modules.users.schemas import UserBrief


class CommentService:
    """Service managing task comments and author permissions."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def create_comment(
        self,
        task_id: uuid.UUID,
        payload: CommentCreate,
        author: User,
    ) -> CommentRead:
        """Create a comment on a task, validating tenant boundary and project access."""
        task = await get_accessible_task(task_id, author, self.db, min_role="MEMBER")

        comment = Comment(
            id=uuid.uuid4(),
            task_id=task.id,
            organization_id=task.organization_id,
            author_id=author.id,
            content=payload.content.strip(),
        )
        self.db.add(comment)
        await self.db.commit()
        await self.db.refresh(comment)

        return CommentRead(
            id=comment.id,
            task_id=comment.task_id,
            organization_id=comment.organization_id,
            author_id=comment.author_id,
            content=comment.content,
            created_at=comment.created_at,
            updated_at=comment.updated_at,
            author=UserBrief.model_validate(author),
        )

    async def list_comments(
        self,
        task_id: uuid.UUID,
        user: User,
    ) -> CommentListResponse:
        """List active comments on a task."""
        await get_accessible_task(task_id, user, self.db, min_role="VIEWER")

        stmt = (
            select(Comment, User)
            .join(User, User.id == Comment.author_id)
            .where(
                Comment.task_id == task_id,
                Comment.deleted_at.is_(None),
            )
            .order_by(Comment.created_at.asc())
        )
        rows = (await self.db.execute(stmt)).all()
        items = [
            CommentRead(
                id=c.id,
                task_id=c.task_id,
                organization_id=c.organization_id,
                author_id=c.author_id,
                content=c.content,
                created_at=c.created_at,
                updated_at=c.updated_at,
                author=UserBrief.model_validate(u),
            )
            for c, u in rows
        ]
        return CommentListResponse(items=items)

    async def _verify_comment_access(
        self,
        comment: Comment,
        user: User,
        min_role: str = "VIEWER",
    ) -> OrganizationMember:
        """Validate that user is an active member of comment's organization and has task access."""
        org_stmt = select(OrganizationMember).where(
            OrganizationMember.organization_id == comment.organization_id,
            OrganizationMember.user_id == user.id,
        )
        org_mem = (await self.db.execute(org_stmt)).scalar_one_or_none()
        if not org_mem:
            raise NotFoundException(code="COMMENT_NOT_FOUND", message="Comment not found.")

        # Validate parent task & project access (concealing non-accessible resources)
        try:
            await get_accessible_task(comment.task_id, user, self.db, min_role=min_role)
        except NotFoundException as exc:
            raise NotFoundException(code="COMMENT_NOT_FOUND", message="Comment not found.") from exc

        return org_mem

    async def update_comment(
        self,
        comment_id: uuid.UUID,
        payload: CommentUpdate,
        user: User,
    ) -> CommentRead:
        """Update comment content. Strictly restricted to active author."""
        stmt = (
            select(Comment, User)
            .join(User, User.id == Comment.author_id)
            .where(
                Comment.id == comment_id,
                Comment.deleted_at.is_(None),
            )
        )
        row = (await self.db.execute(stmt)).one_or_none()
        if not row:
            raise NotFoundException(code="COMMENT_NOT_FOUND", message="Comment not found.")

        comment, author = row

        # Verify active organization membership and parent resource access
        await self._verify_comment_access(comment, user, min_role="MEMBER")

        if comment.author_id != user.id:
            raise ForbiddenException(
                code="NOT_COMMENT_AUTHOR",
                message="Only the author can edit this comment.",
            )

        comment.content = payload.content.strip()
        await self.db.commit()
        await self.db.refresh(comment)

        return CommentRead(
            id=comment.id,
            task_id=comment.task_id,
            organization_id=comment.organization_id,
            author_id=comment.author_id,
            content=comment.content,
            created_at=comment.created_at,
            updated_at=comment.updated_at,
            author=UserBrief.model_validate(author),
        )

    async def delete_comment(
        self,
        comment_id: uuid.UUID,
        user: User,
    ) -> None:
        """Soft-delete comment. Permitted for comment author or organization admin."""
        stmt = select(Comment).where(
            Comment.id == comment_id,
            Comment.deleted_at.is_(None),
        )
        comment = (await self.db.execute(stmt)).scalar_one_or_none()
        if not comment:
            raise NotFoundException(code="COMMENT_NOT_FOUND", message="Comment not found.")

        # Verify active organization membership and parent resource access
        org_mem = await self._verify_comment_access(comment, user, min_role="VIEWER")

        if comment.author_id != user.id:
            if org_mem.role not in (
                OrganizationRole.OWNER,
                OrganizationRole.ADMIN,
                "OWNER",
                "ADMIN",
            ):
                raise ForbiddenException(
                    code="NOT_COMMENT_AUTHOR",
                    message="Only the author or organization admin can delete this comment.",
                )

        comment.deleted_at = utc_now()
        await self.db.commit()
