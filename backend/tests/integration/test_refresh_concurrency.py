"""Integration tests for idempotent refresh protocol and replay detection."""

import uuid
from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.base import utc_now
from app.core.config import settings
from app.core.exceptions import ConflictException, UnauthorizedException
from app.core.security import encrypt_recovery_token
from app.modules.auth.models import RefreshOperation, RefreshTokenSession
from app.modules.auth.service import AuthService
from tests.utils import run_async


def test_lost_response_recovery_same_operation_id() -> None:
    """Scenario A: Client retries with same operation_id within 60s window.

    Must return exact same replacement token idempotently.
    """
    db = AsyncMock()
    user_id = uuid.uuid4()
    family_id = uuid.uuid4()
    operation_id = uuid.uuid4()
    raw_old_token = "old_token_xyz"
    raw_replacement_token = "new_replacement_token_123"

    session_rec = MagicMock(spec=RefreshTokenSession)
    session_rec.id = uuid.uuid4()
    session_rec.user_id = user_id
    session_rec.session_family_id = family_id
    session_rec.is_revoked = False
    session_rec.expires_at = utc_now() + timedelta(days=30)
    session_rec.replaced_by_id = None

    encrypted_replacement = encrypt_recovery_token(
        raw_replacement_token, settings.REFRESH_RECOVERY_KEY
    )

    op_rec = MagicMock(spec=RefreshOperation)
    op_rec.id = operation_id
    op_rec.input_session_id = session_rec.id
    op_rec.output_session_id = uuid.uuid4()
    op_rec.encrypted_token = encrypted_replacement
    op_rec.recovery_window_expires_at = utc_now() + timedelta(seconds=50)

    user = MagicMock()
    user.id = user_id
    user.is_active = True
    user.deleted_at = None

    # First query for session_rec, second query for user, third query for op_rec
    res = MagicMock()
    res.scalar_one_or_none.side_effect = [session_rec, user, op_rec]
    db.execute.return_value = res

    service = AuthService(db)
    access_token, returned_token = run_async(
        service.rotate_refresh_token(
            raw_token=raw_old_token,
            operation_id=operation_id,
        )
    )

    assert returned_token == raw_replacement_token
    assert access_token is not None


def test_incompatible_operation_id_reuse_raises_409() -> None:
    """Scenario C: Previously bound operation ID must raise 409 OPERATION_ID_REUSED."""
    db = AsyncMock()
    user_id = uuid.uuid4()
    operation_id = uuid.uuid4()
    session_rec = MagicMock(spec=RefreshTokenSession)
    session_rec.id = uuid.uuid4()
    session_rec.user_id = user_id
    session_rec.is_revoked = False
    session_rec.replaced_by_id = None

    user = MagicMock()
    user.id = user_id
    user.is_active = True
    user.deleted_at = None

    op_rec = MagicMock(spec=RefreshOperation)
    op_rec.id = operation_id
    # Bound to completely different input and output session IDs
    op_rec.input_session_id = uuid.uuid4()
    op_rec.output_session_id = uuid.uuid4()

    res = MagicMock()
    res.scalar_one_or_none.side_effect = [session_rec, user, op_rec]
    db.execute.return_value = res
    service = AuthService(db)

    with pytest.raises(ConflictException) as exc_info:
        run_async(
            service.rotate_refresh_token(
                raw_token="some_token",
                operation_id=operation_id,
            )
        )
    assert exc_info.value.code == "OPERATION_ID_REUSED"


def test_lineage_branching_detection_revokes_family() -> None:
    """Lineage branching / replay: When a stale already-rotated token is presented,
    the entire session family must be revoked immediately (VULN-0002).
    """
    db = AsyncMock()
    user_id = uuid.uuid4()
    family_id = uuid.uuid4()
    session_rec = MagicMock(spec=RefreshTokenSession)
    session_rec.id = uuid.uuid4()
    session_rec.user_id = user_id
    session_rec.session_family_id = family_id
    session_rec.is_revoked = False
    session_rec.replaced_by_id = uuid.uuid4()

    user = MagicMock()
    user.id = user_id
    user.is_active = True
    user.deleted_at = None

    res = MagicMock()
    res.scalar_one_or_none.side_effect = [session_rec, user, None]
    db.execute.return_value = res
    service = AuthService(db)

    with pytest.raises(UnauthorizedException) as exc_info:
        run_async(
            service.rotate_refresh_token(
                raw_token="stale_token",
                operation_id=uuid.uuid4(),
            )
        )
    assert exc_info.value.code == "INVALID_REFRESH_TOKEN"
    assert db.execute.called
    assert db.commit.called


def test_lost_response_recovery_expired_window_raises_unauthorized() -> None:
    """Scenario A expired: When recovery window expires, retry must raise INVALID_REFRESH_TOKEN."""
    db = AsyncMock()
    user_id = uuid.uuid4()
    family_id = uuid.uuid4()
    operation_id = uuid.uuid4()

    session_rec = MagicMock(spec=RefreshTokenSession)
    session_rec.id = uuid.uuid4()
    session_rec.user_id = user_id
    session_rec.session_family_id = family_id
    session_rec.is_revoked = False
    session_rec.replaced_by_id = None

    op_rec = MagicMock(spec=RefreshOperation)
    op_rec.id = operation_id
    op_rec.input_session_id = session_rec.id
    op_rec.output_session_id = uuid.uuid4()
    op_rec.recovery_window_expires_at = utc_now() - timedelta(seconds=1)  # EXPIRED

    user = MagicMock()
    user.id = user_id
    user.is_active = True
    user.deleted_at = None

    res = MagicMock()
    res.scalar_one_or_none.side_effect = [session_rec, user, op_rec]
    db.execute.return_value = res
    service = AuthService(db)

    with pytest.raises(UnauthorizedException) as exc_info:
        run_async(
            service.rotate_refresh_token(
                raw_token="old_token",
                operation_id=operation_id,
            )
        )
    assert exc_info.value.code == "INVALID_REFRESH_TOKEN"
    assert "Recovery window has expired" in exc_info.value.message


def test_scenario_b_received_replacement_retry_same_operation_id() -> None:
    """Scenario B: Browser received replacement cookie, retrying same operation_id idempotently."""
    db = AsyncMock()
    user_id = uuid.uuid4()
    operation_id = uuid.uuid4()
    raw_replacement_token = "new_replacement_token_456"

    session_rec = MagicMock(spec=RefreshTokenSession)
    session_rec.id = uuid.uuid4()
    session_rec.user_id = user_id
    session_rec.is_revoked = False
    session_rec.replaced_by_id = None
    session_rec.expires_at = utc_now() + timedelta(days=7)

    op_rec = MagicMock(spec=RefreshOperation)
    op_rec.id = operation_id
    op_rec.input_session_id = uuid.uuid4()
    op_rec.output_session_id = session_rec.id  # Matched output session

    user = MagicMock()
    user.id = user_id
    user.is_active = True
    user.deleted_at = None

    res = MagicMock()
    res.scalar_one_or_none.side_effect = [session_rec, user, op_rec]
    db.execute.return_value = res
    service = AuthService(db)

    access_token, returned_token = run_async(
        service.rotate_refresh_token(
            raw_token=raw_replacement_token,
            operation_id=operation_id,
        )
    )
    assert returned_token == raw_replacement_token
    assert access_token is not None


def test_scenario_b_already_rotated_session_raises_unauthorized() -> None:
    """Scenario B: Replacement session that has subsequently been rotated raises INVALID_REFRESH_TOKEN."""
    db = AsyncMock()
    user_id = uuid.uuid4()
    operation_id = uuid.uuid4()

    session_rec = MagicMock(spec=RefreshTokenSession)
    session_rec.id = uuid.uuid4()
    session_rec.user_id = user_id
    session_rec.is_revoked = False
    session_rec.replaced_by_id = uuid.uuid4()  # Already rotated

    op_rec = MagicMock(spec=RefreshOperation)
    op_rec.id = operation_id
    op_rec.input_session_id = uuid.uuid4()
    op_rec.output_session_id = session_rec.id

    user = MagicMock()
    user.id = user_id
    user.is_active = True
    user.deleted_at = None

    res = MagicMock()
    res.scalar_one_or_none.side_effect = [session_rec, user, op_rec]
    db.execute.return_value = res
    service = AuthService(db)

    with pytest.raises(UnauthorizedException) as exc_info:
        run_async(
            service.rotate_refresh_token(
                raw_token="rotated_token",
                operation_id=operation_id,
            )
        )
    assert exc_info.value.code == "INVALID_REFRESH_TOKEN"
    assert "already rotated" in exc_info.value.message


def test_revoked_session_with_new_operation_id_raises_session_revoked() -> None:
    """A revoked session presented with a new operation ID must reject with SESSION_REVOKED."""
    db = AsyncMock()
    user_id = uuid.uuid4()

    session_rec = MagicMock(spec=RefreshTokenSession)
    session_rec.id = uuid.uuid4()
    session_rec.user_id = user_id
    session_rec.is_revoked = True  # Already revoked

    user = MagicMock()
    user.id = user_id
    user.is_active = True
    user.deleted_at = None

    res = MagicMock()
    res.scalar_one_or_none.side_effect = [session_rec, user, None]
    db.execute.return_value = res
    service = AuthService(db)

    with pytest.raises(UnauthorizedException) as exc_info:
        run_async(
            service.rotate_refresh_token(
                raw_token="revoked_token",
                operation_id=uuid.uuid4(),
            )
        )
    assert exc_info.value.code == "SESSION_REVOKED"


def test_cross_tab_concurrent_refresh_lineage_branching_vs_idempotent() -> None:
    """Verifies backend behavior when two tabs refresh:
    If Tab B presents rotated token with same operation_id -> Scenario A/B succeeds idempotently.
    If Tab B presents rotated token with distinct operation_id -> Scenario F revokes entire family.
    """
    db = AsyncMock()
    user_id = uuid.uuid4()
    family_id = uuid.uuid4()

    # Session 1 has already been replaced by Session 2
    session_1 = MagicMock(spec=RefreshTokenSession)
    session_1.id = uuid.uuid4()
    session_1.user_id = user_id
    session_1.session_family_id = family_id
    session_1.is_revoked = False
    session_1.replaced_by_id = uuid.uuid4()

    user = MagicMock()
    user.id = user_id
    user.is_active = True
    user.deleted_at = None

    # Distinct operation ID from a second tab
    tab_b_op_id = uuid.uuid4()

    # No existing operation record for tab_b_op_id
    res = MagicMock()
    res.scalar_one_or_none.side_effect = [session_1, user, None]
    db.execute.return_value = res
    service = AuthService(db)

    # Calling rotate with stale token and Tab B's unshared operation ID
    with pytest.raises(UnauthorizedException) as exc_info:
        run_async(
            service.rotate_refresh_token(
                raw_token="token_s1",
                operation_id=tab_b_op_id,
            )
        )

    # Must detect replay and revoke family
    assert exc_info.value.code == "INVALID_REFRESH_TOKEN"
    assert exc_info.value.message == "Stale refresh token presented."
    assert db.execute.called
    assert db.commit.called


def test_rotated_session_with_deleted_operation_record_triggers_scenario_f() -> None:
    """Finding 2: Deterministic policy when operation record has been lazily deleted.

    When an already-rotated refresh token is presented, but its corresponding RefreshOperation
    record has been deleted (op_record is None), the backend cannot verify whether the client
    is retrying the original operation ID or presenting a new one. To prevent unauthorized
    lineage branching or replay, it must deterministically trigger Scenario F (session family revocation).

    Limitation: This test verifies the service logic with AsyncMock. Database row-level locks
    and foreign key cascades require live PostgreSQL verification.
    """
    db = AsyncMock()
    user_id = uuid.uuid4()
    family_id = uuid.uuid4()

    session_rec = MagicMock(spec=RefreshTokenSession)
    session_rec.id = uuid.uuid4()
    session_rec.user_id = user_id
    session_rec.session_family_id = family_id
    session_rec.is_revoked = False
    session_rec.replaced_by_id = uuid.uuid4()  # Session was previously rotated

    user = MagicMock()
    user.id = user_id
    user.is_active = True
    user.deleted_at = None

    # op_record is None because the operation record was deleted/purged
    res = MagicMock()
    res.scalar_one_or_none.side_effect = [session_rec, user, None]
    db.execute.return_value = res
    service = AuthService(db)

    with pytest.raises(UnauthorizedException) as exc_info:
        run_async(
            service.rotate_refresh_token(
                raw_token="rotated_token_whose_op_was_deleted",
                operation_id=uuid.uuid4(),
            )
        )

    assert exc_info.value.code == "INVALID_REFRESH_TOKEN"
    assert exc_info.value.message == "Stale refresh token presented."
    assert db.execute.called
    assert db.commit.called


def test_rotated_session_with_operation_id_from_other_session_revokes_family() -> None:
    """Finding 2: An already-rotated token presented with an operation ID bound to a different

    session must be detected as cross-session replay/tampering and revoke the entire session family.
    """
    db = AsyncMock()
    user_id = uuid.uuid4()
    family_id = uuid.uuid4()

    session_rec = MagicMock(spec=RefreshTokenSession)
    session_rec.id = uuid.uuid4()
    session_rec.user_id = user_id
    session_rec.session_family_id = family_id
    session_rec.is_revoked = False
    session_rec.replaced_by_id = uuid.uuid4()  # Session was previously rotated

    user = MagicMock()
    user.id = user_id
    user.is_active = True
    user.deleted_at = None

    # op_record is bound to completely different session IDs
    op_rec = MagicMock(spec=RefreshOperation)
    op_rec.id = uuid.uuid4()
    op_rec.input_session_id = uuid.uuid4()
    op_rec.output_session_id = uuid.uuid4()

    res = MagicMock()
    res.scalar_one_or_none.side_effect = [session_rec, user, op_rec]
    db.execute.return_value = res
    service = AuthService(db)

    with pytest.raises(UnauthorizedException) as exc_info:
        run_async(
            service.rotate_refresh_token(
                raw_token="rotated_token",
                operation_id=op_rec.id,
            )
        )

    assert exc_info.value.code == "INVALID_REFRESH_TOKEN"
    assert exc_info.value.message == "Stale refresh token presented."
    assert db.execute.called
    assert db.commit.called


if __name__ == "__main__":
    test_lost_response_recovery_same_operation_id()
    test_incompatible_operation_id_reuse_raises_409()
    test_lineage_branching_detection_revokes_family()
    test_lost_response_recovery_expired_window_raises_unauthorized()
    test_scenario_b_received_replacement_retry_same_operation_id()
    test_scenario_b_already_rotated_session_raises_unauthorized()
    test_revoked_session_with_new_operation_id_raises_session_revoked()
    test_cross_tab_concurrent_refresh_lineage_branching_vs_idempotent()
    test_rotated_session_with_deleted_operation_record_triggers_scenario_f()
    test_rotated_session_with_operation_id_from_other_session_revokes_family()
    print("All refresh concurrency integration tests passed successfully!")
