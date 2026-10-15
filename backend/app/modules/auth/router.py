"""Authentication API router defining registration, login, refresh, and logout endpoints."""

import uuid

from fastapi import APIRouter, Cookie, Depends, Header, Request, Response, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_active_user, get_db
from app.core.exceptions import BadRequestException, UnauthorizedException
from app.core.security import check_auth_rate_limit
from app.modules.auth.schemas import (
    RegisterRequest,
    TokenRefreshResponse,
    TokenResponse,
    UserMeOrganization,
    UserMeResponse,
)
from app.modules.auth.service import AuthService
from app.modules.organizations.models import Organization, OrganizationMember
from app.modules.users.models import User
from app.modules.users.schemas import UserBrief, UserRead

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post(
    "/register",
    status_code=status.HTTP_201_CREATED,
    response_model=UserRead,
    summary="Register a new user",
)
async def register(
    request: Request,
    payload: RegisterRequest,
    db: AsyncSession = Depends(get_db),
) -> User:
    """Register a new user account with Argon2id password hash."""
    await check_auth_rate_limit(request)
    service = AuthService(db)
    return await service.register_user(payload)


@router.post(
    "/token",
    response_model=TokenResponse,
    summary="OAuth2 Password Flow Login",
)
async def login(
    request: Request,
    response: Response,
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: AsyncSession = Depends(get_db),
) -> TokenResponse:
    """Authenticate with username (email) and password, issuing access token and
    HttpOnly refresh cookie.
    """
    await check_auth_rate_limit(request)
    service = AuthService(db)
    ip_address = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")

    user, access_token, raw_refresh_token = await service.authenticate_user(
        email=form_data.username,
        password=form_data.password,
        ip_address=ip_address,
        user_agent=user_agent,
    )

    service.set_refresh_cookie(response, raw_refresh_token)

    return TokenResponse(
        access_token=access_token,
        token_type="bearer",
        expires_in=900,
        user=UserBrief(
            id=user.id,
            email=user.email,
            full_name=user.full_name,
            avatar_url=user.avatar_url,
        ),
    )


@router.post(
    "/refresh",
    response_model=TokenRefreshResponse,
    summary="Rotate refresh token with idempotent recovery",
)
async def refresh_token(
    request: Request,
    response: Response,
    x_refresh_operation_id: str | None = Header(default=None, alias="X-Refresh-Operation-Id"),
    refresh_token: str | None = Cookie(default=None),
    db: AsyncSession = Depends(get_db),
) -> TokenRefreshResponse:
    """Rotate refresh token adhering to the Idempotent Refresh Operation protocol.

    UNIVERSAL SUPPRESSION INVARIANT: Never emits Set-Cookie: Max-Age=0 on any failure.
    """
    if not x_refresh_operation_id:
        raise BadRequestException(
            code="MISSING_OPERATION_ID",
            message="X-Refresh-Operation-Id header is required for refresh operations.",
        )

    try:
        operation_uuid = uuid.UUID(x_refresh_operation_id)
    except ValueError as exc:
        raise BadRequestException(
            code="MALFORMED_OPERATION_ID",
            message="X-Refresh-Operation-Id header must be a valid UUID.",
        ) from exc

    if not refresh_token:
        raise UnauthorizedException(
            code="INVALID_REFRESH_TOKEN",
            message="Refresh token cookie is missing.",
        )

    service = AuthService(db)
    ip_address = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")

    access_token, replacement_raw_token = await service.rotate_refresh_token(
        raw_token=refresh_token,
        operation_id=operation_uuid,
        ip_address=ip_address,
        user_agent=user_agent,
    )

    service.set_refresh_cookie(response, replacement_raw_token)

    return TokenRefreshResponse(
        access_token=access_token,
        token_type="bearer",
        expires_in=900,
    )


@router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Explicit user logout",
)
async def logout(
    response: Response,
    refresh_token: str | None = Cookie(default=None),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Transactionally revoke the session family and exclusively clear the refresh cookie."""
    service = AuthService(db)
    await service.logout_session(refresh_token)
    service.clear_refresh_cookie(response)


@router.get(
    "/me",
    response_model=UserMeResponse,
    summary="Get current user profile and memberships",
)
async def get_me(
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> UserMeResponse:
    """Return the profile and organizations of the currently authenticated user."""
    stmt = (
        select(
            Organization.id,
            Organization.name,
            Organization.slug,
            OrganizationMember.role,
        )
        .join(OrganizationMember, OrganizationMember.organization_id == Organization.id)
        .where(
            OrganizationMember.user_id == current_user.id,
            Organization.deleted_at.is_(None),
        )
    )
    result = await db.execute(stmt)
    rows = result.all()

    orgs = [
        UserMeOrganization(
            id=row[0],
            name=row[1],
            slug=row[2],
            role=row[3],
        )
        for row in rows
    ]

    return UserMeResponse(
        id=current_user.id,
        email=current_user.email,
        full_name=current_user.full_name,
        avatar_url=current_user.avatar_url,
        organizations=orgs,
    )
