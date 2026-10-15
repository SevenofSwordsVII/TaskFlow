"""Stage B: Authentication persistence, rotation lineage, replay detection, and revocation."""

import asyncio
import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.exceptions import UnauthorizedException
from app.core.security import hash_password, hash_token
from app.modules.auth.models import RefreshOperation, RefreshTokenSession
from app.modules.auth.service import AuthService
from app.modules.users.models import User


async def _create_test_user(session: AsyncSession, email: str = "auth_test@taskflow.dev") -> User:
    """Helper to create and persist an active test user."""
    user = User(
        id=uuid.uuid4(),
        email=email,
        full_name="Auth Test User",
        hashed_password=hash_password("SuperSecretPassword123!"),
        is_active=True,
    )
    session.add(user)
    await session.commit()
    return user


@pytest.mark.asyncio
async def test_authenticate_persists_refresh_session(db_session: AsyncSession) -> None:
    """Verify authenticating user persists a valid RefreshTokenSession record in PostgreSQL."""
    await _create_test_user(db_session, "login_persist@taskflow.dev")
    auth_service = AuthService(db_session)

    user, access_token, raw_refresh_token = await auth_service.authenticate_user(
        email="login_persist@taskflow.dev",
        password="SuperSecretPassword123!",
    )

    assert user is not None
    assert access_token is not None
    assert raw_refresh_token is not None

    token_hash = hash_token(raw_refresh_token)
    stmt = select(RefreshTokenSession).where(RefreshTokenSession.token_hash == token_hash)
    session_record = (await db_session.execute(stmt)).scalar_one_or_none()

    assert session_record is not None
    assert session_record.user_id == user.id
    assert session_record.is_revoked is False
    assert session_record.replaced_by_id is None


@pytest.mark.asyncio
async def test_refresh_token_rotation_lineage_and_operations(db_session: AsyncSession) -> None:
    """Verify token rotation persists replacement session and records RefreshOperation."""
    await _create_test_user(db_session, "rotate_test@taskflow.dev")
    auth_service = AuthService(db_session)

    _, _, raw_token_1 = await auth_service.authenticate_user(
        email="rotate_test@taskflow.dev",
        password="SuperSecretPassword123!",
    )

    op_id = uuid.uuid4()
    access_token_2, raw_token_2 = await auth_service.rotate_refresh_token(
        raw_token=raw_token_1,
        operation_id=op_id,
    )

    assert access_token_2 is not None
    assert raw_token_2 != raw_token_1

    # Check old session lineage
    hash_1 = hash_token(raw_token_1)
    s1 = (
        await db_session.execute(
            select(RefreshTokenSession).where(RefreshTokenSession.token_hash == hash_1)
        )
    ).scalar_one()

    # Check new session
    hash_2 = hash_token(raw_token_2)
    s2 = (
        await db_session.execute(
            select(RefreshTokenSession).where(RefreshTokenSession.token_hash == hash_2)
        )
    ).scalar_one()

    assert s1.replaced_by_id == s2.id
    assert s1.session_family_id == s2.session_family_id
    assert s2.is_revoked is False

    # Check refresh operation record
    op = (
        await db_session.execute(select(RefreshOperation).where(RefreshOperation.id == op_id))
    ).scalar_one_or_none()
    assert op is not None
    assert op.input_session_id == s1.id
    assert op.output_session_id == s2.id


@pytest.mark.asyncio
async def test_idempotent_retry_returns_same_token(db_session: AsyncSession) -> None:
    """Verify in-flight retry with same operation_id returns exact replacement token."""
    await _create_test_user(db_session, "retry_test@taskflow.dev")
    auth_service = AuthService(db_session)

    _, _, raw_token_1 = await auth_service.authenticate_user(
        email="retry_test@taskflow.dev",
        password="SuperSecretPassword123!",
    )

    op_id = uuid.uuid4()
    _, initial_replacement = await auth_service.rotate_refresh_token(
        raw_token=raw_token_1,
        operation_id=op_id,
    )

    # Retry using same operation_id and old raw token
    _, retry_replacement = await auth_service.rotate_refresh_token(
        raw_token=raw_token_1,
        operation_id=op_id,
    )

    assert retry_replacement == initial_replacement


@pytest.mark.asyncio
async def test_stale_token_replay_revokes_entire_session_family(db_session: AsyncSession) -> None:
    """Verify presentation of already-rotated token revokes all sessions in family."""
    await _create_test_user(db_session, "replay_test@taskflow.dev")
    auth_service = AuthService(db_session)

    _, _, token_1 = await auth_service.authenticate_user(
        email="replay_test@taskflow.dev",
        password="SuperSecretPassword123!",
    )

    op_1 = uuid.uuid4()
    _, token_2 = await auth_service.rotate_refresh_token(
        raw_token=token_1,
        operation_id=op_1,
    )

    # Replay token_1 with a new operation ID (simulating token theft/replay)
    op_attacker = uuid.uuid4()
    with pytest.raises(UnauthorizedException) as exc_info:
        await auth_service.rotate_refresh_token(
            raw_token=token_1,
            operation_id=op_attacker,
        )

    assert exc_info.value.code == "INVALID_REFRESH_TOKEN"
    assert "Stale" in exc_info.value.message

    # Verify both sessions in family are revoked in the database
    hash_1 = hash_token(token_1)
    hash_2 = hash_token(token_2)

    s1 = (
        await db_session.execute(
            select(RefreshTokenSession).where(RefreshTokenSession.token_hash == hash_1)
        )
    ).scalar_one()
    s2 = (
        await db_session.execute(
            select(RefreshTokenSession).where(RefreshTokenSession.token_hash == hash_2)
        )
    ).scalar_one()

    assert s1.is_revoked is True
    assert s2.is_revoked is True


@pytest.mark.asyncio
async def test_concurrent_competing_refresh_requests(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Verify concurrent refresh requests with independent connections lock and maintain integrity."""
    async with session_factory() as setup_session:
        await _create_test_user(setup_session, "competing@taskflow.dev")
        auth_service = AuthService(setup_session)
        _, _, raw_token = await auth_service.authenticate_user(
            email="competing@taskflow.dev",
            password="SuperSecretPassword123!",
        )

    # Run two concurrent rotations on independent sessions/connections with different operation IDs
    async def _rotate(op_id: uuid.UUID) -> tuple[bool, str | None]:
        async with session_factory() as session:
            srv = AuthService(session)
            try:
                _, new_tok = await srv.rotate_refresh_token(
                    raw_token=raw_token,
                    operation_id=op_id,
                )
                return True, new_tok
            except UnauthorizedException as exc:
                return False, exc.code

    op_a = uuid.uuid4()
    op_b = uuid.uuid4()

    res_a, res_b = await asyncio.gather(
        _rotate(op_a),
        _rotate(op_b),
        return_exceptions=False,
    )

    # One must succeed and the other must be rejected (or trigger replay revocation)
    successes = [r for r in [res_a, res_b] if r[0] is True]
    failures = [r for r in [res_a, res_b] if r[0] is False]

    assert len(successes) == 1, f"Expected exactly 1 success, got {len(successes)}"
    assert len(failures) == 1, f"Expected exactly 1 failure, got {len(failures)}"
    assert failures[0][1] in ("INVALID_REFRESH_TOKEN", "SESSION_REVOKED")
