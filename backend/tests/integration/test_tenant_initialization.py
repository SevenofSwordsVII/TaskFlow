"""Integration tests for tenant initialization, slug uniqueness, and OWNER assignment."""

import uuid
from unittest.mock import AsyncMock, MagicMock

from app.core.exceptions import ConflictException
from app.modules.organizations.models import Organization, OrganizationRole
from app.modules.organizations.schemas import OrganizationCreate
from app.modules.organizations.service import OrganizationService
from app.modules.users.models import User
from tests.utils import run_async


def test_create_organization_assigns_owner_role() -> None:
    """User creating organization must be assigned OWNER role atomically."""
    db = AsyncMock()
    db.add = MagicMock()
    # Slug lookup returns None (slug not taken)
    db.execute.return_value = MagicMock(scalar_one_or_none=MagicMock(return_value=None))

    creator = User(
        id=uuid.uuid4(),
        email="creator@example.com",
        full_name="Creator",
        is_active=True,
    )

    service = OrganizationService(db)
    payload = OrganizationCreate(name="Acme Corp", slug="acme-corp")

    res = run_async(service.create_organization(payload, creator=creator))
    assert res.role == OrganizationRole.OWNER.value
    assert res.slug == "acme-corp"
    assert db.add.call_count >= 2  # Added Organization and OrganizationMember
    assert db.commit.called


def test_duplicate_organization_slug_raises_409() -> None:
    """Duplicate organization slug must raise 409 Conflict."""
    db = AsyncMock()
    existing_org = MagicMock(spec=Organization)
    db.execute.return_value = MagicMock(scalar_one_or_none=MagicMock(return_value=existing_org))

    creator = User(
        id=uuid.uuid4(),
        email="creator@example.com",
        full_name="Creator",
        is_active=True,
    )

    service = OrganizationService(db)
    payload = OrganizationCreate(name="Acme Corp", slug="acme-corp")

    try:
        run_async(service.create_organization(payload, creator=creator))
        assert False, "Expected ConflictException"
    except ConflictException as exc:
        assert exc.code == "ORGANIZATION_SLUG_EXISTS"


if __name__ == "__main__":
    test_create_organization_assigns_owner_role()
    test_duplicate_organization_slug_raises_409()
    print("All tenant initialization integration tests passed successfully!")
