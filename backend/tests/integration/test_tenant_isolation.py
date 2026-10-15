"""Integration tests for tenant defense and cross-tenant 404 Not Found concealment."""

import uuid
from unittest.mock import AsyncMock, MagicMock

from app.core.dependencies import require_org_role, require_project_access
from app.core.exceptions import NotFoundException
from app.modules.organizations.models import OrganizationRole
from app.modules.users.models import User
from tests.utils import run_async


def test_cross_tenant_organization_concealment_returns_404() -> None:
    """TENANT CONCEALMENT INVARIANT:

    Non-membership in an organization MUST raise 404 Not Found, NEVER 403 Forbidden,
    preventing unauthorized existence enumeration.
    """
    db = AsyncMock()
    # Member lookup returns None (user does not belong to organization)
    db.execute.return_value = MagicMock(scalar_one_or_none=MagicMock(return_value=None))

    user = User(
        id=uuid.uuid4(),
        email="outsider@example.com",
        full_name="Outsider",
        is_active=True,
    )
    org_id = uuid.uuid4()

    dependency_fn = require_org_role(OrganizationRole.MEMBER)

    try:
        run_async(dependency_fn(organization_id=org_id, current_user=user, db=db))
        assert False, "Expected NotFoundException"
    except NotFoundException as exc:
        assert exc.code == "ORGANIZATION_NOT_FOUND"
        assert exc.status_code == 404


def test_restricted_project_concealment_returns_404() -> None:
    """Accessing a project outside tenant or restricted project without membership must return 404."""
    db = AsyncMock()
    db.execute.return_value = MagicMock(scalar_one_or_none=MagicMock(return_value=None))

    user = User(
        id=uuid.uuid4(),
        email="outsider@example.com",
        full_name="Outsider",
        is_active=True,
    )
    project_id = uuid.uuid4()

    dependency_fn = require_project_access("VIEWER")

    try:
        run_async(dependency_fn(project_id=project_id, current_user=user, db=db))
        assert False, "Expected NotFoundException"
    except NotFoundException as exc:
        assert exc.code == "PROJECT_NOT_FOUND"
        assert exc.status_code == 404


if __name__ == "__main__":
    test_cross_tenant_organization_concealment_returns_404()
    test_restricted_project_concealment_returns_404()
    print("All tenant isolation integration tests passed successfully!")
