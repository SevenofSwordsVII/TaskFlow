"""Unit tests for organization invitation acceptance, email verification, and error precedence."""

import hashlib
import uuid
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

from app.core.base import utc_now
from app.core.exceptions import (
    BadRequestException,
    ConflictException,
    ForbiddenException,
    NotFoundException,
)
from app.modules.organizations.models import (
    Organization,
    OrganizationInvitation,
    OrganizationMember,
    OrganizationRole,
)
from app.modules.organizations.service import OrganizationService
from app.modules.users.models import User
from tests.utils import run_async


def create_mock_user(email: str) -> User:
    user = MagicMock(spec=User)
    user.id = uuid.uuid4()
    user.email = email
    return user


def create_invitation(
    email: str = "invited@example.com",
    token: str = "valid_secret_token",
    accepted_at: datetime | None = None,
    revoked_at: datetime | None = None,
    expired_at: datetime | None = None,
    is_expired_by_time: bool = False,
) -> tuple[OrganizationInvitation, str]:
    now = utc_now()
    inv = MagicMock(spec=OrganizationInvitation)
    inv.id = uuid.uuid4()
    inv.organization_id = uuid.uuid4()
    inv.email = email
    inv.role = OrganizationRole.MEMBER
    inv.token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    inv.accepted_at = accepted_at
    inv.revoked_at = revoked_at
    inv.expired_at = expired_at
    if is_expired_by_time:
        inv.expires_at = now - timedelta(days=1)
    else:
        inv.expires_at = now + timedelta(days=7)
    return inv, token


def test_invitation_not_found() -> None:
    db = AsyncMock()
    db.execute.return_value = MagicMock(scalar_one_or_none=MagicMock(return_value=None))
    service = OrganizationService(db)
    user = create_mock_user("invited@example.com")

    try:
        run_async(service.accept_invitation("non_existent_token", user))
        assert False, "Expected NotFoundException"
    except NotFoundException as exc:
        assert exc.code == "INVITATION_NOT_FOUND"


def test_invitation_already_accepted() -> None:
    inv, token = create_invitation(accepted_at=utc_now())
    db = AsyncMock()
    db.execute.return_value = MagicMock(scalar_one_or_none=MagicMock(return_value=inv))
    service = OrganizationService(db)
    user = create_mock_user("invited@example.com")

    try:
        run_async(service.accept_invitation(token, user))
        assert False, "Expected BadRequestException"
    except BadRequestException as exc:
        assert exc.code == "INVITATION_ALREADY_ACCEPTED"


def test_invitation_revoked() -> None:
    inv, token = create_invitation(revoked_at=utc_now())
    db = AsyncMock()
    db.execute.return_value = MagicMock(scalar_one_or_none=MagicMock(return_value=inv))
    service = OrganizationService(db)
    user = create_mock_user("invited@example.com")

    try:
        run_async(service.accept_invitation(token, user))
        assert False, "Expected BadRequestException"
    except BadRequestException as exc:
        assert exc.code == "INVITATION_REVOKED"


def test_invitation_expired() -> None:
    inv, token = create_invitation(is_expired_by_time=True)
    db = AsyncMock()
    db.execute.return_value = MagicMock(scalar_one_or_none=MagicMock(return_value=inv))
    service = OrganizationService(db)
    user = create_mock_user("invited@example.com")

    try:
        run_async(service.accept_invitation(token, user))
        assert False, "Expected BadRequestException"
    except BadRequestException as exc:
        assert exc.code == "INVITATION_EXPIRED"


def test_invitation_email_mismatch_forbidden() -> None:
    inv, token = create_invitation(email="target@example.com")
    db = AsyncMock()
    db.execute.return_value = MagicMock(scalar_one_or_none=MagicMock(return_value=inv))
    service = OrganizationService(db)
    # Different user email attempts to claim token
    malicious_user = create_mock_user("attacker@example.com")

    try:
        run_async(service.accept_invitation(token, malicious_user))
        assert False, "Expected ForbiddenException"
    except ForbiddenException as exc:
        assert exc.code == "INVITATION_EMAIL_MISMATCH"


def test_invitation_email_case_insensitive_match_and_already_member() -> None:
    inv, token = create_invitation(email="User.Name@Example.COM")
    db = AsyncMock()
    # First query returns inv, second query returns existing member
    existing_mem = MagicMock(spec=OrganizationMember)
    db.execute.return_value = MagicMock(
        scalar_one_or_none=MagicMock(side_effect=[inv, existing_mem])
    )
    service = OrganizationService(db)
    user = create_mock_user("user.name@example.com")

    try:
        run_async(service.accept_invitation(token, user))
        assert False, "Expected ConflictException"
    except ConflictException as exc:
        assert exc.code == "ALREADY_MEMBER"


def test_invitation_acceptance_success() -> None:
    inv, token = create_invitation(email="Invited.Member@Example.com")
    org = MagicMock(spec=Organization)
    org.id = inv.organization_id
    org.name = "Acme Corp"
    org.slug = "acme"
    org.is_archived = False
    org.created_at = utc_now()
    org.updated_at = utc_now()

    db = AsyncMock()
    db.add = MagicMock()
    # First query returns inv, second returns None (not existing member), third returns org
    exec_mock = MagicMock()
    exec_mock.scalar_one_or_none.side_effect = [inv, None]
    exec_mock.scalar_one.return_value = org
    db.execute.return_value = exec_mock

    service = OrganizationService(db)
    user = create_mock_user("invited.member@example.com")

    res = run_async(service.accept_invitation(token, user))
    assert res.id == org.id
    assert inv.accepted_at is not None
    assert db.add.call_count >= 2  # Added member and audit log
    assert db.commit.called


if __name__ == "__main__":
    test_invitation_not_found()
    test_invitation_already_accepted()
    test_invitation_revoked()
    test_invitation_expired()
    test_invitation_email_mismatch_forbidden()
    test_invitation_email_case_insensitive_match_and_already_member()
    test_invitation_acceptance_success()
    print("All invitation acceptance unit tests passed successfully!")
