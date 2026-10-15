"""Comprehensive security and functionality integration tests for SQLAdmin.

Verifies:
1. Anonymous access rejection and redirect to login.
2. Ordinary user denial (is_superuser=False).
3. Organization Owner / Admin denial (workspace roles do not confer global superuser privileges).
4. Legitimate global administrator authentication success.
5. Session clearance on logout.
6. Rejection of invalid, tampered, deactivated, or demoted admin sessions.
7. ModelView registration and sensitive field exclusion (hashed_password, token_hash).
8. Immutability of governance audit logs.
9. Idempotent CLI management commands (create-superuser, promote-user, demote-user).
"""

import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from starlette.requests import Request
from starlette.responses import RedirectResponse

from app.admin.auth import TaskFlowAdminAuth
from app.admin.setup import setup_admin
from app.admin.views import (
    ALL_ADMIN_VIEWS,
    AuditLogAdmin,
    OrganizationInvitationAdmin,
    RefreshTokenSessionAdmin,
    UserAdmin,
)
from app.cli import create_superuser, demote_user, promote_user
from app.core.security import hash_password
from app.modules.auth.models import RefreshTokenSession
from app.modules.organizations.models import OrganizationInvitation
from app.modules.users.models import User
from tests.utils import run_async


def create_mock_request(
    form_data: dict[str, str] | None = None,
    session_data: dict[str, Any] | None = None,
    client_ip: str = "127.0.0.1",
) -> MagicMock:
    """Helper to instantiate mock Starlette Request with session and form data."""
    request = MagicMock(spec=Request)
    request.client = MagicMock(host=client_ip)
    request.session = dict(session_data or {})

    async def get_form() -> dict[str, str]:
        return form_data or {}

    request.form = get_form
    request.url_for = MagicMock(return_value="/admin/login")
    return request


def test_admin_auth_anonymous_access_redirects_to_login() -> None:
    """1. Anonymous requests without session must be redirected to /admin/login."""
    auth = TaskFlowAdminAuth()
    request = create_mock_request(session_data={})

    result = run_async(auth.authenticate(request))
    assert isinstance(result, RedirectResponse)
    assert result.status_code == 302
    assert result.headers["location"] == "/admin/login"


def test_admin_auth_ordinary_user_login_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    """2. Ordinary authenticated users (is_superuser=False) cannot log into SQLAdmin."""
    auth = TaskFlowAdminAuth()
    plain_password = "Password123!"

    ordinary_user = User(
        id=uuid.uuid4(),
        email="member@example.com",
        full_name="Ordinary Member",
        hashed_password=hash_password(plain_password),
        is_active=True,
        is_superuser=False,  # NOT SUPERUSER
    )

    mock_db = AsyncMock()
    mock_db.execute.return_value = MagicMock(
        scalar_one_or_none=MagicMock(return_value=ordinary_user)
    )
    monkeypatch.setattr("app.admin.auth.AsyncSessionLocal", MagicMock(return_value=mock_db))
    mock_db.__aenter__.return_value = mock_db

    request = create_mock_request(
        form_data={"username": "member@example.com", "password": plain_password},
        client_ip="192.168.1.10",
    )

    result = run_async(auth.login(request))
    assert result is False
    assert "admin_user_id" not in request.session


def test_admin_auth_organization_owner_without_superuser_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """3. Organization Owners without global superuser status are denied SQLAdmin access."""
    auth = TaskFlowAdminAuth()
    plain_password = "OwnerPassword123!"

    org_owner = User(
        id=uuid.uuid4(),
        email="owner@startup.com",
        full_name="Company Owner",
        hashed_password=hash_password(plain_password),
        is_active=True,
        is_superuser=False,  # Workspace OWNER, but NOT global site superuser
    )

    mock_db = AsyncMock()
    mock_db.execute.return_value = MagicMock(scalar_one_or_none=MagicMock(return_value=org_owner))
    monkeypatch.setattr("app.admin.auth.AsyncSessionLocal", MagicMock(return_value=mock_db))
    mock_db.__aenter__.return_value = mock_db

    request = create_mock_request(
        form_data={"username": "owner@startup.com", "password": plain_password},
        client_ip="192.168.1.11",
    )

    result = run_async(auth.login(request))
    assert result is False
    assert "admin_user_id" not in request.session


def test_admin_auth_organization_admin_without_superuser_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """4. Organization Admins without global superuser status are denied SQLAdmin access."""
    auth = TaskFlowAdminAuth()
    plain_password = "AdminPassword123!"

    org_admin = User(
        id=uuid.uuid4(),
        email="admin@startup.com",
        full_name="Company Admin",
        hashed_password=hash_password(plain_password),
        is_active=True,
        is_superuser=False,  # Workspace ADMIN, but NOT global site superuser
    )

    mock_db = AsyncMock()
    mock_db.execute.return_value = MagicMock(scalar_one_or_none=MagicMock(return_value=org_admin))
    monkeypatch.setattr("app.admin.auth.AsyncSessionLocal", MagicMock(return_value=mock_db))
    mock_db.__aenter__.return_value = mock_db

    request = create_mock_request(
        form_data={"username": "admin@startup.com", "password": plain_password},
        client_ip="192.168.1.12",
    )

    result = run_async(auth.login(request))
    assert result is False
    assert "admin_user_id" not in request.session


def test_admin_auth_global_superuser_login_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    """5. Legitimate global administrator can authenticate and obtain an admin session."""
    auth = TaskFlowAdminAuth()
    plain_password = "GlobalAdminPassword123!"
    admin_id = uuid.uuid4()

    superuser = User(
        id=admin_id,
        email="root@taskflow.dev",
        full_name="Global Superuser",
        hashed_password=hash_password(plain_password),
        is_active=True,
        is_superuser=True,  # PROPER GLOBAL SUPERUSER
    )

    mock_db = AsyncMock()
    mock_db.execute.return_value = MagicMock(scalar_one_or_none=MagicMock(return_value=superuser))
    monkeypatch.setattr("app.admin.auth.AsyncSessionLocal", MagicMock(return_value=mock_db))
    mock_db.__aenter__.return_value = mock_db

    request = create_mock_request(
        form_data={"username": "root@taskflow.dev", "password": plain_password},
        client_ip="192.168.1.13",
    )

    result = run_async(auth.login(request))
    assert result is True
    assert request.session.get("admin_user_id") == str(admin_id)
    assert request.session.get("admin_email") == "root@taskflow.dev"
    assert request.session.get("is_superuser") is True


def test_admin_auth_logout_clears_session() -> None:
    """6. Logout clears session contents completely."""
    auth = TaskFlowAdminAuth()
    request = create_mock_request(
        session_data={
            "admin_user_id": str(uuid.uuid4()),
            "admin_email": "root@taskflow.dev",
            "is_superuser": True,
        }
    )

    result = run_async(auth.logout(request))
    assert result is True
    assert len(request.session) == 0


def test_admin_auth_authenticate_valid_session(monkeypatch: pytest.MonkeyPatch) -> None:
    """7. Active superuser session passes authentication."""
    auth = TaskFlowAdminAuth()
    admin_id = uuid.uuid4()

    superuser = User(
        id=admin_id,
        email="root@taskflow.dev",
        is_active=True,
        is_superuser=True,
    )

    mock_db = AsyncMock()
    mock_db.execute.return_value = MagicMock(scalar_one_or_none=MagicMock(return_value=superuser))
    monkeypatch.setattr("app.admin.auth.AsyncSessionLocal", MagicMock(return_value=mock_db))
    mock_db.__aenter__.return_value = mock_db

    request = create_mock_request(session_data={"admin_user_id": str(admin_id)})

    result = run_async(auth.authenticate(request))
    assert result is True


def test_admin_auth_authenticate_deactivated_user_revokes_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """8. If superuser account is deactivated in database, session is revoked immediately."""
    auth = TaskFlowAdminAuth()
    admin_id = uuid.uuid4()

    deactivated_superuser = User(
        id=admin_id,
        email="root@taskflow.dev",
        is_active=False,  # DEACTIVATED ACCOUNT
        is_superuser=True,
    )

    mock_db = AsyncMock()
    mock_db.execute.return_value = MagicMock(
        scalar_one_or_none=MagicMock(return_value=deactivated_superuser)
    )
    monkeypatch.setattr("app.admin.auth.AsyncSessionLocal", MagicMock(return_value=mock_db))
    mock_db.__aenter__.return_value = mock_db

    request = create_mock_request(session_data={"admin_user_id": str(admin_id)})

    result = run_async(auth.authenticate(request))
    assert isinstance(result, RedirectResponse)
    assert len(request.session) == 0  # Session cleared


def test_admin_auth_authenticate_demoted_user_revokes_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """9. If user is demoted from superuser in database, session is revoked immediately."""
    auth = TaskFlowAdminAuth()
    admin_id = uuid.uuid4()

    demoted_user = User(
        id=admin_id,
        email="former_root@taskflow.dev",
        is_active=True,
        is_superuser=False,  # DEMOTED FROM SUPERUSER
    )

    mock_db = AsyncMock()
    mock_db.execute.return_value = MagicMock(
        scalar_one_or_none=MagicMock(return_value=demoted_user)
    )
    monkeypatch.setattr("app.admin.auth.AsyncSessionLocal", MagicMock(return_value=mock_db))
    mock_db.__aenter__.return_value = mock_db

    request = create_mock_request(session_data={"admin_user_id": str(admin_id)})

    result = run_async(auth.authenticate(request))
    assert isinstance(result, RedirectResponse)
    assert len(request.session) == 0


def test_admin_views_registration_and_model_count() -> None:
    """10. Verify all 13 core models have views registered in SQLAdmin."""
    mock_app = MagicMock()
    mock_engine = MagicMock()

    admin = setup_admin(mock_app, mock_engine)
    assert len(admin.views) == len(ALL_ADMIN_VIEWS)
    assert len(admin.views) == 13


def test_admin_views_sensitive_fields_excluded() -> None:
    """11. Verify password hashes and token secrets are excluded from admin views and forms."""
    # UserAdmin must not expose password hash in detail view or form
    assert User.hashed_password in UserAdmin.column_details_exclude_list
    assert User.hashed_password in UserAdmin.form_excluded_columns
    assert User.hashed_password not in UserAdmin.column_list

    # OrganizationInvitationAdmin must not expose token hash
    assert (
        OrganizationInvitation.token_hash in OrganizationInvitationAdmin.column_details_exclude_list
    )
    assert OrganizationInvitation.token_hash not in OrganizationInvitationAdmin.column_list

    # RefreshTokenSessionAdmin must not expose token hash
    assert RefreshTokenSession.token_hash in RefreshTokenSessionAdmin.column_details_exclude_list
    assert RefreshTokenSession.token_hash in RefreshTokenSessionAdmin.form_excluded_columns
    assert RefreshTokenSession.token_hash not in RefreshTokenSessionAdmin.column_list


def test_admin_audit_logs_strictly_immutable() -> None:
    """12. Governance audit logs must be strictly read-only."""
    assert AuditLogAdmin.can_create is False
    assert AuditLogAdmin.can_edit is False
    assert AuditLogAdmin.can_delete is False


def test_cli_create_superuser_and_idempotency(monkeypatch: pytest.MonkeyPatch) -> None:
    """13. CLI create-superuser provisions new admin or idempotently updates existing user."""
    mock_db = AsyncMock()
    mock_db.add = MagicMock()
    mock_db.execute.return_value = MagicMock(scalar_one_or_none=MagicMock(return_value=None))
    monkeypatch.setattr("app.cli.AsyncSessionLocal", MagicMock(return_value=mock_db))
    mock_db.__aenter__.return_value = mock_db

    # 1. New user creation
    run_async(create_superuser("new_admin@taskflow.dev", "SecurePassword123!", "Admin"))
    assert mock_db.add.called
    assert mock_db.commit.called

    # 2. Idempotent promotion of existing user
    existing_user = User(
        id=uuid.uuid4(),
        email="existing@taskflow.dev",
        is_active=True,
        is_superuser=False,
    )
    mock_db.execute.return_value = MagicMock(
        scalar_one_or_none=MagicMock(return_value=existing_user)
    )

    run_async(create_superuser("existing@taskflow.dev", "NewPassword123!"))
    assert existing_user.is_superuser is True
    assert existing_user.is_active is True


def test_cli_promote_and_demote_user(monkeypatch: pytest.MonkeyPatch) -> None:
    """14. CLI promote-user and demote-user toggle is_superuser accurately."""
    user = User(
        id=uuid.uuid4(),
        email="test_toggle@taskflow.dev",
        is_active=True,
        is_superuser=False,
    )
    mock_db = AsyncMock()
    mock_db.execute.return_value = MagicMock(scalar_one_or_none=MagicMock(return_value=user))
    monkeypatch.setattr("app.cli.AsyncSessionLocal", MagicMock(return_value=mock_db))
    mock_db.__aenter__.return_value = mock_db

    # Promote
    run_async(promote_user("test_toggle@taskflow.dev"))
    assert user.is_superuser is True

    # Demote
    run_async(demote_user("test_toggle@taskflow.dev"))
    assert user.is_superuser is False
