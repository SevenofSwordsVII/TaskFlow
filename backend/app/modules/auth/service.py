"""Authentication domain service handling credentials, tokens, and sessions."""

import secrets
import uuid
from datetime import timedelta
from typing import Literal, cast

from fastapi import Response
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.base import utc_now
from app.core.config import settings
from app.core.exceptions import (
    BadRequestException,
    ConflictException,
    UnauthorizedException,
)
from app.core.security import (
    create_access_token,
    decrypt_recovery_token,
    encrypt_recovery_token,
    hash_password,
    hash_token,
    verify_password,
)
from app.modules.auth.models import RefreshOperation, RefreshTokenSession
from app.modules.auth.schemas import RegisterRequest
from app.modules.users.models import User


class AuthService:
    """Service encapsulating user authentication and refresh session lifecycles."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def register_user(self, payload: RegisterRequest) -> User:
        """Register a new user with Argon2id password hash."""
        email_clean = payload.email.strip().lower()
        stmt = select(User).where(
            func.lower(User.email) == email_clean,
            User.deleted_at.is_(None),
        )
        existing = (await self.db.execute(stmt)).scalar_one_or_none()
        if existing:
            raise BadRequestException(
                code="EMAIL_ALREADY_EXISTS",
                message="Email already registered.",
            )

        hashed_pw = hash_password(payload.password)
        user = User(
            id=uuid.uuid4(),
            email=email_clean,
            full_name=payload.full_name.strip(),
            hashed_password=hashed_pw,
            is_active=True,
            is_superuser=False,
        )
        self.db.add(user)
        await self.db.commit()
        await self.db.refresh(user)
        return user

    async def authenticate_user(
        self,
        email: str,
        password: str,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> tuple[User, str, str]:
        """Authenticate user and issue new session family with access & refresh tokens."""
        email_clean = email.strip().lower()
        stmt = select(User).where(
            func.lower(User.email) == email_clean,
            User.deleted_at.is_(None),
        )
        user = (await self.db.execute(stmt)).scalar_one_or_none()

        if not user or not verify_password(password, user.hashed_password):
            raise UnauthorizedException(
                code="INVALID_CREDENTIALS",
                message="Invalid email or password.",
            )

        if not user.is_active:
            raise UnauthorizedException(
                code="ACCOUNT_INACTIVE",
                message="Account is inactive.",
            )

        raw_refresh_token = secrets.token_urlsafe(64)
        token_hash = hash_token(raw_refresh_token)
        session_family_id = uuid.uuid4()
        expires_at = utc_now() + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)

        session = RefreshTokenSession(
            id=uuid.uuid4(),
            user_id=user.id,
            token_hash=token_hash,
            session_family_id=session_family_id,
            is_revoked=False,
            replaced_by_id=None,
            expires_at=expires_at,
            ip_address=ip_address,
            user_agent=user_agent,
            created_at=utc_now(),
        )
        self.db.add(session)
        await self.db.commit()

        access_token = create_access_token(
            subject=str(user.id),
            expires_delta=timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
        )
        return user, access_token, raw_refresh_token

    async def rotate_refresh_token(
        self,
        raw_token: str,
        operation_id: uuid.UUID,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> tuple[str, str]:
        """Rotate refresh token adhering to the Idempotent Refresh Operation protocol."""
        token_hash = hash_token(raw_token)

        stmt = (
            select(RefreshTokenSession)
            .where(RefreshTokenSession.token_hash == token_hash)
            .with_for_update()
        )
        session_record = (await self.db.execute(stmt)).scalar_one_or_none()

        if not session_record:
            raise UnauthorizedException(
                code="INVALID_REFRESH_TOKEN",
                message="Invalid refresh token.",
            )

        # VULN-0001: Validate principal active status from database
        user_stmt = select(User).where(
            User.id == session_record.user_id,
            User.deleted_at.is_(None),
        )
        user = (await self.db.execute(user_stmt)).scalar_one_or_none()
        if not user or not user.is_active:
            # Transactionally revoke entire session family to terminate access
            await self.db.execute(
                update(RefreshTokenSession)
                .where(RefreshTokenSession.session_family_id == session_record.session_family_id)
                .values(is_revoked=True)
            )
            await self.db.commit()
            raise UnauthorizedException(
                code="ACCOUNT_INACTIVE",
                message="Account is inactive or deleted.",
            )

        op_stmt = (
            select(RefreshOperation).where(RefreshOperation.id == operation_id).with_for_update()
        )
        op_record = (await self.db.execute(op_stmt)).scalar_one_or_none()

        if op_record:
            if op_record.input_session_id == session_record.id:
                # Scenario A: In-flight or lost response retry with same operation_id
                if session_record.is_revoked:
                    raise UnauthorizedException(
                        code="SESSION_REVOKED",
                        message="Session has been revoked.",
                    )
                if utc_now() > op_record.recovery_window_expires_at:
                    raise UnauthorizedException(
                        code="INVALID_REFRESH_TOKEN",
                        message="Recovery window has expired.",
                    )
                raw_replacement = decrypt_recovery_token(
                    op_record.encrypted_token,
                    settings.REFRESH_RECOVERY_KEY,
                )
                access_token = create_access_token(
                    subject=str(session_record.user_id),
                    expires_delta=timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
                )
                return access_token, raw_replacement

            if op_record.output_session_id == session_record.id:
                # Scenario B: Browser received replacement cookie, retrying same operation_id
                if session_record.is_revoked:
                    raise UnauthorizedException(
                        code="SESSION_REVOKED",
                        message="Session has been revoked.",
                    )
                if session_record.replaced_by_id is not None:
                    raise UnauthorizedException(
                        code="INVALID_REFRESH_TOKEN",
                        message="Session already rotated.",
                    )
                if utc_now() >= session_record.expires_at:
                    raise UnauthorizedException(
                        code="SESSION_EXPIRED",
                        message="Session has expired.",
                    )
                access_token = create_access_token(
                    subject=str(session_record.user_id),
                    expires_delta=timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
                )
                return access_token, raw_token

            # Incompatible reuse: operation ID bound to different session
            if session_record.replaced_by_id is not None:
                # Stale token presented with an operation ID belonging to another session:
                # Lineage branching / token replay detected: immediately revoke
                # entire session family
                family_id = session_record.session_family_id
                await self.db.execute(
                    update(RefreshTokenSession)
                    .where(RefreshTokenSession.session_family_id == family_id)
                    .values(is_revoked=True)
                )
                await self.db.commit()
                raise UnauthorizedException(
                    code="INVALID_REFRESH_TOKEN",
                    message="Stale refresh token presented.",
                )

            raise ConflictException(
                code="OPERATION_ID_REUSED",
                message=(
                    "Operation ID was previously bound to an incompatible session "
                    "and cannot be reused."
                ),
            )

        # New Operation ID (op_record is None)
        if session_record.is_revoked:
            raise UnauthorizedException(
                code="SESSION_REVOKED",
                message="Session has been revoked.",
            )

        if session_record.replaced_by_id is not None:
            # Scenario F: Stale replaced token with mismatched or deleted operation ID
            # Lineage branching / token replay detected: immediately revoke entire session family
            await self.db.execute(
                update(RefreshTokenSession)
                .where(RefreshTokenSession.session_family_id == session_record.session_family_id)
                .values(is_revoked=True)
            )
            await self.db.commit()
            raise UnauthorizedException(
                code="INVALID_REFRESH_TOKEN",
                message="Stale refresh token presented.",
            )

        if utc_now() >= session_record.expires_at:
            raise UnauthorizedException(
                code="SESSION_EXPIRED",
                message="Session has expired. Please log in again.",
            )

        # Normal Rotation Flow
        new_raw_token = secrets.token_urlsafe(64)
        new_token_hash = hash_token(new_raw_token)
        new_session = RefreshTokenSession(
            id=uuid.uuid4(),
            user_id=session_record.user_id,
            token_hash=new_token_hash,
            session_family_id=session_record.session_family_id,
            is_revoked=False,
            replaced_by_id=None,
            expires_at=utc_now() + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
            ip_address=ip_address,
            user_agent=user_agent,
            created_at=utc_now(),
        )
        self.db.add(new_session)
        await self.db.flush()

        session_record.replaced_by_id = new_session.id

        encrypted_token = encrypt_recovery_token(
            new_raw_token,
            settings.REFRESH_RECOVERY_KEY,
        )
        recovery_op = RefreshOperation(
            id=operation_id,
            user_id=session_record.user_id,
            session_family_id=session_record.session_family_id,
            input_session_id=session_record.id,
            output_session_id=new_session.id,
            encrypted_token=encrypted_token,
            recovery_window_expires_at=utc_now() + timedelta(seconds=60),
            created_at=utc_now(),
        )
        self.db.add(recovery_op)

        # Lazy cleanup: retain operations for a 24-hour audit and replay-classification window
        # rather than eagerly deleting them at 60 seconds. This ensures retrying the original
        # operation after the recovery window expires is deterministically recognized as an
        # expired retry (Scenario A timeout) rather than misclassified as a token replay
        # (Scenario F).
        await self.db.execute(
            delete(RefreshOperation).where(
                RefreshOperation.user_id == session_record.user_id,
                RefreshOperation.recovery_window_expires_at < utc_now() - timedelta(hours=24),
            )
        )
        await self.db.commit()

        access_token = create_access_token(
            subject=str(session_record.user_id),
            expires_delta=timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
        )
        return access_token, new_raw_token

    async def logout_session(self, raw_token: str | None) -> None:
        """Revoke entire session family upon explicit user logout."""
        if not raw_token:
            return
        token_hash = hash_token(raw_token)
        stmt = select(RefreshTokenSession).where(RefreshTokenSession.token_hash == token_hash)
        session_record = (await self.db.execute(stmt)).scalar_one_or_none()
        if session_record:
            await self.db.execute(
                update(RefreshTokenSession)
                .where(RefreshTokenSession.session_family_id == session_record.session_family_id)
                .values(is_revoked=True)
            )
            await self.db.commit()

    @staticmethod
    def set_refresh_cookie(response: Response, raw_token: str) -> None:
        """Set HttpOnly refresh token cookie on response."""
        samesite_mode = cast(Literal["lax", "strict", "none"], settings.SAME_SITE.lower())
        response.set_cookie(
            key="refresh_token",
            value=raw_token,
            httponly=True,
            secure=settings.COOKIE_SECURE,
            samesite=samesite_mode,
            path="/api/v1/auth",
            max_age=settings.REFRESH_TOKEN_EXPIRE_DAYS * 86400,
        )

    @staticmethod
    def clear_refresh_cookie(response: Response) -> None:
        """Exclusively clear refresh cookie on explicit user logout."""
        samesite_mode = cast(Literal["lax", "strict", "none"], settings.SAME_SITE.lower())
        response.delete_cookie(
            key="refresh_token",
            path="/api/v1/auth",
            httponly=True,
            secure=settings.COOKIE_SECURE,
            samesite=samesite_mode,
        )
