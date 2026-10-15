"""Users API router for profile management and account deletion."""

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_active_user, get_db
from app.modules.users.models import User
from app.modules.users.schemas import UserRead, UserUpdate
from app.modules.users.service import UserService

router = APIRouter(prefix="/users", tags=["users"])


@router.get(
    "/me",
    response_model=UserRead,
    summary="Get current user profile",
)
async def get_my_profile(
    current_user: User = Depends(get_current_active_user),
) -> UserRead:
    """Return profile details of the authenticated caller."""
    return UserRead.model_validate(current_user)


@router.patch(
    "/me",
    response_model=UserRead,
    summary="Update current user profile",
)
async def update_my_profile(
    payload: UserUpdate,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> UserRead:
    """Update profile details for the authenticated user."""
    service = UserService(db)
    return await service.update_profile(current_user.id, payload)


@router.delete(
    "/me",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete user account",
)
async def delete_my_account(
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Execute ordered account deletion respecting ON DELETE RESTRICT on session relations."""
    service = UserService(db)
    await service.delete_account(current_user.id)
