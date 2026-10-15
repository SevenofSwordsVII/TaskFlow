"""SQLAdmin authentication backend for TaskFlow global site administration."""

from __future__ import annotations

import logging
import uuid
from typing import Any

from fastapi import status
from sqladmin.authentication import AuthenticationBackend
from sqlalchemy import func, select
from starlette.requests import Request
from starlette.responses import RedirectResponse, Response

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.core.security import auth_rate_limiter, verify_password
from app.modules.users.models import User

logger = logging.getLogger("app.admin.auth")


# Server-side revoked session IDs registry to invalidate replayed cookies after logout
_REVOKED_ADMIN_SESSIONS: set[str] = set()


class TaskFlowAdminAuth(AuthenticationBackend):
    """Session-based authentication backend for SQLAdmin.

    Enforces strict server-side authorization: only active users with
    is_superuser=True can access the administration interface. Organization-level
    owners or admins without global superuser status are strictly denied.
    """

    def __init__(self) -> None:
        super().__init__(
            secret_key=settings.effective_admin_secret_key,
            session_cookie="taskflow_admin_session",
            max_age=14400,  # 4 hours session lifetime
            same_site=settings.SAME_SITE,
            https_only=settings.COOKIE_SECURE,
        )

    async def login(self, request: Request) -> bool:
        """Authenticate global superuser credentials."""
        client_ip = request.client.host if request.client else "127.0.0.1"
        rate_key = f"admin_login:{client_ip}"
        if not auth_rate_limiter.is_allowed(rate_key, max_requests=10, window_seconds=60.0):
            logger.warning("Admin login rate limit exceeded for IP: %s", client_ip)
            return False

        form = await request.form()
        username = form.get("username")
        password = form.get("password")

        if (
            not username
            or not password
            or not isinstance(username, str)
            or not isinstance(password, str)
        ):
            return False

        email = username.strip().lower()

        async with AsyncSessionLocal() as session:
            stmt = (
                select(User)
                .where(
                    func.lower(User.email) == email,
                    User.deleted_at.is_(None),
                )
                .limit(1)
            )
            result = await session.execute(stmt)
            user = result.scalar_one_or_none()

            if not user:
                logger.warning("Admin login failed: user not found for email %s", email)
                return False

            if not verify_password(password, user.hashed_password):
                logger.warning("Admin login failed: invalid password for email %s", email)
                return False

            if not user.is_active:
                logger.warning("Admin login failed: account deactivated for email %s", email)
                return False

            if not user.is_superuser:
                logger.warning(
                    "Admin login rejected: non-superuser access attempt by %s (is_superuser=False)",
                    email,
                )
                return False

            session_id = str(uuid.uuid4())
            request.session.update(
                {
                    "session_id": session_id,
                    "admin_user_id": str(user.id),
                    "admin_email": user.email,
                    "is_superuser": True,
                }
            )
            logger.info("Admin login successful for superuser: %s (session %s)", email, session_id)
            return True

    async def logout(self, request: Request) -> bool:
        """Clear admin session on logout and track server-side revocation."""
        session_id = request.session.get("session_id")
        if session_id:
            _REVOKED_ADMIN_SESSIONS.add(str(session_id))
            # Bound the memory footprint
            if len(_REVOKED_ADMIN_SESSIONS) > 50000:
                _REVOKED_ADMIN_SESSIONS.clear()
        request.session.clear()
        return True

    async def authenticate(self, request: Request) -> Response | bool:
        """Validate active admin session and verify superuser privileges against the database."""
        session_id = request.session.get("session_id")
        if session_id and str(session_id) in _REVOKED_ADMIN_SESSIONS:
            logger.warning("Revoked admin session replayed: %s", session_id)
            request.session.clear()
            return RedirectResponse(
                request.url_for("admin:login"), status_code=status.HTTP_302_FOUND
            )

        admin_user_id_str = request.session.get("admin_user_id")
        if not admin_user_id_str:
            return RedirectResponse(
                request.url_for("admin:login"), status_code=status.HTTP_302_FOUND
            )

        try:
            admin_user_id = uuid.UUID(str(admin_user_id_str))
        except (ValueError, TypeError):
            request.session.clear()
            return RedirectResponse(
                request.url_for("admin:login"), status_code=status.HTTP_302_FOUND
            )

        async with AsyncSessionLocal() as session:
            stmt = (
                select(User)
                .where(
                    User.id == admin_user_id,
                    User.deleted_at.is_(None),
                )
                .limit(1)
            )
            result = await session.execute(stmt)
            user = result.scalar_one_or_none()

            if not user or not user.is_active or not user.is_superuser:
                logger.warning(
                    "Admin session revoked for user_id %s: inactive, deleted, or demoted",
                    admin_user_id,
                )
                request.session.clear()
                return RedirectResponse(
                    request.url_for("admin:login"), status_code=status.HTTP_302_FOUND
                )

        return True

    async def get_user_id(self, request: Request) -> Any:
        """Return the authenticated admin user's ID."""
        return request.session.get("admin_user_id")
