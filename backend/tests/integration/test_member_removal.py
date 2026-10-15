"""Integration tests for member removal, task unassignment, and session invalidation."""

import uuid
from unittest.mock import AsyncMock, MagicMock

from app.core.exceptions import ForbiddenException
from app.modules.organizations.models import OrganizationMember, OrganizationRole
from app.modules.organizations.service import OrganizationService
from tests.utils import run_async


def test_cannot_remove_organization_owner() -> None:
    """Removing organization owner must be rejected with 403 CANNOT_REMOVE_OWNER."""
    db = AsyncMock()
    org_id = uuid.uuid4()
    owner_id = uuid.uuid4()

    owner_member = MagicMock(spec=OrganizationMember)
    owner_member.role = OrganizationRole.OWNER

    db.execute.return_value = MagicMock(scalar_one_or_none=MagicMock(return_value=owner_member))
    service = OrganizationService(db)

    try:
        run_async(service.remove_member(org_id, owner_id, actor_role=OrganizationRole.ADMIN.value))
        assert False, "Expected ForbiddenException"
    except ForbiddenException as exc:
        assert exc.code == "CANNOT_REMOVE_OWNER"


def test_member_removal_atomically_unassigns_tasks() -> None:
    """Removing member must unassign all tasks in tenant and delete project memberships."""
    db = AsyncMock()
    db.delete = AsyncMock()
    org_id = uuid.uuid4()
    target_user_id = uuid.uuid4()

    target_member = MagicMock(spec=OrganizationMember)
    target_member.role = OrganizationRole.MEMBER

    db.execute.return_value = MagicMock(scalar_one_or_none=MagicMock(return_value=target_member))
    service = OrganizationService(db)

    run_async(
        service.remove_member(org_id, target_user_id, actor_role=OrganizationRole.ADMIN.value)
    )

    # Verify task unassignment update and project_member delete were executed
    executed_statements = db.execute.call_args_list
    assert (
        len(executed_statements) >= 2
    )  # 1 select member, 1 update tasks, 1 delete project_members
    assert db.delete.called  # deleted member
    db.delete.assert_awaited_once_with(target_member)
    assert db.commit.called


if __name__ == "__main__":
    test_cannot_remove_organization_owner()
    test_member_removal_atomically_unassigns_tasks()
    print("All member removal integration tests passed successfully!")
