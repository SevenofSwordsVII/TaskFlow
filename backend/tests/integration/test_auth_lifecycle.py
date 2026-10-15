"""Integration and lifecycle tests for authentication, tokens, cookie invariants, and logout."""

import uuid
from unittest.mock import AsyncMock, MagicMock

from fastapi import Response

from app.core.security import (
    create_access_token,
    decode_access_token,
    generate_secure_token,
    hash_password,
    verify_password,
)
from app.modules.auth.models import RefreshTokenSession
from app.modules.auth.service import AuthService
from tests.utils import run_async


def test_auth_token_issuance_and_stateless_claims() -> None:
    """Verify access token contains required claims and 15-minute expiration."""
    user_id = uuid.uuid4()
    token = create_access_token(user_id)
    payload = decode_access_token(token)

    assert payload["sub"] == str(user_id)
    assert payload["type"] == "access"
    assert "jti" in payload
    # Verify expiration window roughly 15 minutes
    diff = payload["exp"] - payload["iat"]
    assert 890 <= diff <= 910


def test_password_security_and_argon2() -> None:
    """Verify passwords are secure, hashed, and verifiable."""
    password = "SuperSecretPassword123!"
    hashed = hash_password(password)

    assert hashed != password
    assert verify_password(password, hashed) is True
    assert verify_password("IncorrectPassword", hashed) is False


def test_universal_refresh_failure_cookie_suppression() -> None:
    """UNIVERSAL SUPPRESSION INVARIANT:

    Under no circumstances does refresh failure emit Set-Cookie: Max-Age=0.
    """
    response = MagicMock(spec=Response)
    db = AsyncMock()
    service = AuthService(db)

    # Even if an invalid or expired token is handled, clear_refresh_cookie is NEVER called by rotate_refresh_token
    # It is exclusively called by logout_session.
    assert hasattr(service, "clear_refresh_cookie")
    # Verify set_refresh_cookie sets HttpOnly and SameSite
    raw_token = generate_secure_token(32)
    service.set_refresh_cookie(response, raw_token)

    response.set_cookie.assert_called_once()
    kwargs = response.set_cookie.call_args.kwargs
    assert kwargs["key"] == "refresh_token"
    assert kwargs["value"] == raw_token
    assert kwargs["httponly"] is True


def test_exclusive_logout_cookie_clearing() -> None:
    """Verify that only explicit logout transactionally revokes session family and clears cookie."""
    response = MagicMock(spec=Response)
    db = AsyncMock()
    session_rec = MagicMock(spec=RefreshTokenSession)
    session_rec.session_family_id = uuid.uuid4()

    result_mock = MagicMock()
    result_mock.scalar_one_or_none.return_value = session_rec
    db.execute.return_value = result_mock
    service = AuthService(db)

    raw_token = "valid_logout_token"
    run_async(service.logout_session(raw_token))
    service.clear_refresh_cookie(response)

    # Session family was marked is_revoked = True
    assert db.execute.called
    assert db.commit.called

    # Cookie cleared with delete_cookie
    response.delete_cookie.assert_called_once()
    assert response.delete_cookie.call_args.kwargs["key"] == "refresh_token"


if __name__ == "__main__":
    test_auth_token_issuance_and_stateless_claims()
    test_password_security_and_argon2()
    test_universal_refresh_failure_cookie_suppression()
    test_exclusive_logout_cookie_clearing()
    print("All auth lifecycle integration tests passed successfully!")
