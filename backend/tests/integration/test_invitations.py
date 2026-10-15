"""Integration tests for organization member invitations, email matching, and acceptance lifecycle."""

import hashlib
import uuid
from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock

from app.core.base import utc_now
from app.core.exceptions import (
    ConflictException,
    ForbiddenException,
)
from app.modules.organizations.models import (
    Organization,
    OrganizationInvitation,
    OrganizationRole,
)
from app.modules.organizations.schemas import InvitationCreate
from app.modules.organizations.service import OrganizationService
from app.modules.users.models import User
from tests.utils import run_async


def test_create_invitation_stores_sha256_hash() -> None:
    """Raw invitation token must not be stored in DB; SHA-256 hash must be stored instead."""
    db = AsyncMock()
    db.add = MagicMock()
    # Member lookup returns None (user not yet member), active inv lookup returns None
    exec_mock = MagicMock()
    exec_mock.scalar_one_or_none.side_effect = [None, None]
    db.execute.return_value = exec_mock

    inviter = User(
        id=uuid.uuid4(),
        email="inviter@example.com",
        full_name="Inviter",
        is_active=True,
    )
    org_id = uuid.uuid4()
    payload = InvitationCreate(email="newuser@example.com", role=OrganizationRole.MEMBER)

    service = OrganizationService(db)
    res = run_async(service.create_invitation(org_id, payload, inviter=inviter))

    assert res.email == "newuser@example.com"
    assert res.invitation_token is not None
    # Verify token added to db had SHA-256 hash
    added_inv = db.add.call_args[0][0]
    expected_hash = hashlib.sha256(res.invitation_token.encode("utf-8")).hexdigest()
    assert added_inv.token_hash == expected_hash
    assert db.commit.called


def test_duplicate_pending_invitation_raises_409() -> None:
    """Duplicate pending active invitation must raise 409 PENDING_INVITATION_EXISTS."""
    db = AsyncMock()
    active_inv = MagicMock(spec=OrganizationInvitation)
    active_inv.expires_at = utc_now() + timedelta(days=5)

    exec_mock = MagicMock()
    exec_mock.scalar_one_or_none.side_effect = [None, active_inv]
    db.execute.return_value = exec_mock

    inviter = User(
        id=uuid.uuid4(), email="inviter@example.com", full_name="Inviter", is_active=True
    )
    service = OrganizationService(db)
    payload = InvitationCreate(email="duplicate@example.com", role=OrganizationRole.MEMBER)

    try:
        run_async(service.create_invitation(uuid.uuid4(), payload, inviter=inviter))
        assert False, "Expected ConflictException"
    except ConflictException as exc:
        assert exc.code == "PENDING_INVITATION_EXISTS"


def test_accept_invitation_email_mismatch_returns_403() -> None:
    """Authenticated caller email must strictly match invitation email; mismatch returns 403 INVITATION_EMAIL_MISMATCH."""
    raw_token = "secure_token_value"
    token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()

    inv = MagicMock(spec=OrganizationInvitation)
    inv.token_hash = token_hash
    inv.email = "target.user@example.com"
    inv.accepted_at = None
    inv.revoked_at = None
    inv.expired_at = None
    inv.expires_at = utc_now() + timedelta(days=5)

    db = AsyncMock()
    db.execute.return_value = MagicMock(scalar_one_or_none=MagicMock(return_value=inv))
    service = OrganizationService(db)

    # Calling user has different email
    user = User(
        id=uuid.uuid4(),
        email="different.person@example.com",
        full_name="Attacker",
        is_active=True,
    )

    try:
        run_async(service.accept_invitation(raw_token, user=user))
        assert False, "Expected ForbiddenException"
    except ForbiddenException as exc:
        assert exc.code == "INVITATION_EMAIL_MISMATCH"


def test_accept_invitation_matching_email_succeeds() -> None:
    """Matching email (case-insensitive) creates membership and marks accepted_at."""
    raw_token = "secure_token_value"
    token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()

    org_id = uuid.uuid4()
    inv = MagicMock(spec=OrganizationInvitation)
    inv.organization_id = org_id
    inv.token_hash = token_hash
    inv.email = "Target.User@Example.COM"
    inv.role = OrganizationRole.MEMBER
    inv.accepted_at = None
    inv.revoked_at = None
    inv.expired_at = None
    inv.expires_at = utc_now() + timedelta(days=5)

    org = MagicMock(spec=Organization)
    org.id = org_id
    org.name = "Test Org"
    org.slug = "test-org"
    org.is_archived = False
    org.created_at = utc_now()
    org.updated_at = utc_now()

    db = AsyncMock()
    db.add = MagicMock()
    exec_mock = MagicMock()
    exec_mock.scalar_one_or_none.side_effect = [inv, None]  # inv, not already member
    exec_mock.scalar_one.return_value = org
    db.execute.return_value = exec_mock

    service = OrganizationService(db)
    user = User(
        id=uuid.uuid4(),
        email="target.user@example.com",
        full_name="Target",
        is_active=True,
    )

    res = run_async(service.accept_invitation(raw_token, user=user))
    assert res.id == org_id
    assert inv.accepted_at is not None
    assert db.commit.called


if __name__ == "__main__":
    test_create_invitation_stores_sha256_hash()
    test_duplicate_pending_invitation_raises_409()
    test_accept_invitation_email_mismatch_returns_403()
    test_accept_invitation_matching_email_succeeds()
    print("All invitation integration tests passed successfully!")
