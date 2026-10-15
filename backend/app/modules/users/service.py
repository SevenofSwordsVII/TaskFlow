"""User domain service managing profile updates and ordered account deletion."""

import uuid

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.base import utc_now
from app.core.exceptions import NotFoundException
from app.modules.auth.models import RefreshOperation, RefreshTokenSession
from app.modules.users.models import User
from app.modules.users.schemas import UserRead, UserUpdate


class UserService:
    """Service handling user account lifecycle, profile updates, and ordered account deletion."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_by_id(self, user_id: uuid.UUID) -> User:
        """Fetch active user by UUID."""
        stmt = select(User).where(User.id == user_id, User.deleted_at.is_(None))
        user = (await self.db.execute(stmt)).scalar_one_or_none()
        if not user:
            raise NotFoundException(code="USER_NOT_FOUND", message="User not found.")
        return user

    async def update_profile(self, user_id: uuid.UUID, payload: UserUpdate) -> UserRead:
        """Update user profile fields."""
        user = await self.get_by_id(user_id)
        if payload.full_name is not None:
            user.full_name = payload.full_name.strip()
        if payload.avatar_url is not None:
            user.avatar_url = payload.avatar_url.strip() if payload.avatar_url else None

        await self.db.commit()
        await self.db.refresh(user)
        return UserRead.model_validate(user)

    async def delete_account(self, user_id: uuid.UUID, hard_delete: bool = False) -> None:
        """Execute ordered account deletion respecting ON DELETE RESTRICT constraints.

        Order within single transaction:
        1. DELETE FROM refresh_operations WHERE user_id = :user_id;
        2. DELETE FROM refresh_token_sessions WHERE user_id = :user_id;
        3. DELETE or soft-delete user record.
        """
        # Verify user exists
        user = await self.get_by_id(user_id)

        # 1. Delete refresh operations first to satisfy ON DELETE RESTRICT on session FKs
        await self.db.execute(delete(RefreshOperation).where(RefreshOperation.user_id == user_id))

        # 2. Delete refresh token sessions
        await self.db.execute(
            delete(RefreshTokenSession).where(RefreshTokenSession.user_id == user_id)
        )

        # 3. Finalize user deletion
        if hard_delete:
            await self.db.delete(user)
        else:
            user.deleted_at = utc_now()
            user.is_active = False

        await self.db.commit()
