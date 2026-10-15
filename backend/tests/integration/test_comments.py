"""Integration tests for task comments creation, author-only editing, and soft-deletion."""

import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.exceptions import ForbiddenException, NotFoundException
from app.modules.comments.models import Comment
from app.modules.comments.schemas import CommentUpdate
from app.modules.comments.service import CommentService
from app.modules.kanban.models import Task
from app.modules.organizations.models import OrganizationMember, OrganizationRole
from app.modules.projects.models import Project, ProjectMember, ProjectRole, ProjectVisibility
from app.modules.users.models import User
from tests.utils import run_async


def _setup_mock_db(
    comment: Comment,
    author: User,
    user_org_member: OrganizationMember | None,
    task: Task | None = None,
    project: Project | None = None,
    project_member: ProjectMember | None = None,
) -> AsyncMock:
    """Helper to mock db.execute returning appropriate responses for comment operations."""
    db = AsyncMock()
    # Explicitly mock synchronous SQLAlchemy methods to prevent unawaited coroutine warnings
    db.add = MagicMock()
    db.delete = MagicMock()

    def execute_side_effect(stmt: Any) -> MagicMock:
        stmt_str = str(stmt)
        mock_result = MagicMock()

        # Comment lookup: select(Comment, User)
        if "comments" in stmt_str and "users" in stmt_str:
            mock_result.one_or_none.return_value = (comment, author)
            return mock_result

        # Comment single lookup: select(Comment)
        if "comments" in stmt_str:
            mock_result.scalar_one_or_none.return_value = comment
            return mock_result

        # OrganizationMember lookup: select(OrganizationMember)
        if "organization_members" in stmt_str:
            mock_result.scalar_one_or_none.return_value = user_org_member
            return mock_result

        # ProjectMember lookup: select(ProjectMember)
        if "project_members" in stmt_str:
            mock_result.scalar_one_or_none.return_value = project_member
            return mock_result

        # Task & Project lookup in get_accessible_task: select(Task, Project)
        if "tasks" in stmt_str and "projects" in stmt_str:
            if task is not None and project is not None:
                mock_result.one_or_none.return_value = (task, project)
            else:
                mock_result.one_or_none.return_value = None
            return mock_result

        mock_result.scalar_one_or_none.return_value = None
        mock_result.one_or_none.return_value = None
        return mock_result

    db.execute.side_effect = execute_side_effect
    return db


def test_comment_author_edit_success() -> None:
    """Active authorized author can update their comment in an organization-public project."""
    author_id = uuid.uuid4()
    org_id = uuid.uuid4()
    task_id = uuid.uuid4()
    project_id = uuid.uuid4()
    comment_id = uuid.uuid4()

    author = User(
        id=author_id,
        email="author@example.com",
        full_name="Author",
        is_active=True,
    )
    comment = MagicMock(spec=Comment)
    comment.id = comment_id
    comment.organization_id = org_id
    comment.task_id = task_id
    comment.author_id = author_id
    comment.author = author
    comment.content = "Original content"
    comment.created_at = "2026-10-11T00:00:00Z"
    comment.updated_at = "2026-10-11T00:00:00Z"

    org_member = MagicMock(
        spec=OrganizationMember,
        organization_id=org_id,
        user_id=author_id,
        role=OrganizationRole.MEMBER,
    )
    task = MagicMock(spec=Task, id=task_id, project_id=project_id, organization_id=org_id)
    project = MagicMock(
        spec=Project,
        id=project_id,
        organization_id=org_id,
        visibility=ProjectVisibility.ORG_PUBLIC,
    )

    db = _setup_mock_db(comment, author, org_member, task, project)
    service = CommentService(db)
    payload = CommentUpdate(content="Updated content")

    updated_res = run_async(service.update_comment(comment_id, payload, user=author))
    assert updated_res.content == "Updated content"
    assert comment.content == "Updated content"
    assert db.commit.called


def test_former_member_cannot_update_historical_comment() -> None:
    """A former member whose membership was revoked cannot update their comment (404 NOT FOUND)."""
    author_id = uuid.uuid4()
    org_id = uuid.uuid4()
    comment_id = uuid.uuid4()

    former_member = User(
        id=author_id,
        email="former@example.com",
        full_name="Former Member",
        is_active=True,
    )
    comment = MagicMock(spec=Comment)
    comment.id = comment_id
    comment.organization_id = org_id
    comment.task_id = uuid.uuid4()
    comment.author_id = author_id
    comment.content = "Historical comment"

    # user_org_member is None (removed from organization)
    db = _setup_mock_db(comment, former_member, user_org_member=None)
    service = CommentService(db)
    payload = CommentUpdate(content="Tampered after removal")

    with pytest.raises(NotFoundException) as exc_info:
        run_async(service.update_comment(comment_id, payload, user=former_member))
    assert exc_info.value.code == "COMMENT_NOT_FOUND"


def test_former_member_cannot_delete_historical_comment() -> None:
    """A former member cannot delete their historical comment after membership revocation (404 NOT FOUND)."""
    author_id = uuid.uuid4()
    org_id = uuid.uuid4()
    comment_id = uuid.uuid4()

    former_member = User(
        id=author_id,
        email="former@example.com",
        full_name="Former Member",
        is_active=True,
    )
    comment = MagicMock(spec=Comment)
    comment.id = comment_id
    comment.organization_id = org_id
    comment.task_id = uuid.uuid4()
    comment.author_id = author_id

    # user_org_member is None
    db = _setup_mock_db(comment, former_member, user_org_member=None)
    service = CommentService(db)

    with pytest.raises(NotFoundException) as exc_info:
        run_async(service.delete_comment(comment_id, user=former_member))
    assert exc_info.value.code == "COMMENT_NOT_FOUND"


def test_unauthorized_member_cannot_update_other_user_comment() -> None:
    """An active organization member cannot edit another user's comment (403 FORBIDDEN)."""
    author_id = uuid.uuid4()
    other_user_id = uuid.uuid4()
    org_id = uuid.uuid4()
    task_id = uuid.uuid4()
    project_id = uuid.uuid4()
    comment_id = uuid.uuid4()

    author = User(id=author_id, email="author@example.com", full_name="Author", is_active=True)
    other_user = User(
        id=other_user_id,
        email="other@example.com",
        full_name="Other Member",
        is_active=True,
    )
    comment = MagicMock(spec=Comment)
    comment.id = comment_id
    comment.organization_id = org_id
    comment.task_id = task_id
    comment.author_id = author_id

    org_member = MagicMock(
        spec=OrganizationMember,
        organization_id=org_id,
        user_id=other_user_id,
        role=OrganizationRole.MEMBER,
    )
    task = MagicMock(spec=Task, id=task_id, project_id=project_id, organization_id=org_id)
    project = MagicMock(
        spec=Project,
        id=project_id,
        organization_id=org_id,
        visibility=ProjectVisibility.ORG_PUBLIC,
    )

    db = _setup_mock_db(comment, author, org_member, task, project)
    service = CommentService(db)
    payload = CommentUpdate(content="Tampered by other member")

    with pytest.raises(ForbiddenException) as exc_info:
        run_async(service.update_comment(comment_id, payload, user=other_user))
    assert exc_info.value.code == "NOT_COMMENT_AUTHOR"


def test_admin_cannot_edit_other_user_comment() -> None:
    """An organization administrator cannot edit another user's comment text (403 FORBIDDEN)."""
    author_id = uuid.uuid4()
    admin_id = uuid.uuid4()
    org_id = uuid.uuid4()
    task_id = uuid.uuid4()
    project_id = uuid.uuid4()
    comment_id = uuid.uuid4()

    author = User(id=author_id, email="author@example.com", full_name="Author", is_active=True)
    admin_user = User(
        id=admin_id,
        email="admin@example.com",
        full_name="Org Admin",
        is_active=True,
    )
    comment = MagicMock(spec=Comment)
    comment.id = comment_id
    comment.organization_id = org_id
    comment.task_id = task_id
    comment.author_id = author_id

    admin_org_member = MagicMock(
        spec=OrganizationMember,
        organization_id=org_id,
        user_id=admin_id,
        role=OrganizationRole.ADMIN,
    )
    task = MagicMock(spec=Task, id=task_id, project_id=project_id, organization_id=org_id)
    project = MagicMock(
        spec=Project,
        id=project_id,
        organization_id=org_id,
        visibility=ProjectVisibility.ORG_PUBLIC,
    )

    db = _setup_mock_db(comment, author, admin_org_member, task, project)
    service = CommentService(db)
    payload = CommentUpdate(content="Admin attempting to edit author comment")

    with pytest.raises(ForbiddenException) as exc_info:
        run_async(service.update_comment(comment_id, payload, user=admin_user))
    assert exc_info.value.code == "NOT_COMMENT_AUTHOR"


def test_admin_can_delete_other_user_comment() -> None:
    """An organization administrator can delete another user's comment."""
    author_id = uuid.uuid4()
    admin_id = uuid.uuid4()
    org_id = uuid.uuid4()
    task_id = uuid.uuid4()
    project_id = uuid.uuid4()
    comment_id = uuid.uuid4()

    author = User(id=author_id, email="author@example.com", full_name="Author", is_active=True)
    admin_user = User(
        id=admin_id,
        email="admin@example.com",
        full_name="Org Admin",
        is_active=True,
    )
    comment = MagicMock(spec=Comment)
    comment.id = comment_id
    comment.organization_id = org_id
    comment.task_id = task_id
    comment.author_id = author_id

    admin_org_member = MagicMock(
        spec=OrganizationMember,
        organization_id=org_id,
        user_id=admin_id,
        role=OrganizationRole.ADMIN,
    )
    task = MagicMock(spec=Task, id=task_id, project_id=project_id, organization_id=org_id)
    project = MagicMock(
        spec=Project,
        id=project_id,
        organization_id=org_id,
        visibility=ProjectVisibility.ORG_PUBLIC,
    )

    db = _setup_mock_db(comment, author, admin_org_member, task, project)
    service = CommentService(db)

    run_async(service.delete_comment(comment_id, user=admin_user))
    assert comment.deleted_at is not None
    assert db.commit.called


def test_regular_member_cannot_delete_other_user_comment() -> None:
    """A regular member cannot delete another user's comment (403 FORBIDDEN)."""
    author_id = uuid.uuid4()
    other_user_id = uuid.uuid4()
    org_id = uuid.uuid4()
    task_id = uuid.uuid4()
    project_id = uuid.uuid4()
    comment_id = uuid.uuid4()

    author = User(id=author_id, email="author@example.com", full_name="Author", is_active=True)
    other_user = User(
        id=other_user_id,
        email="other@example.com",
        full_name="Other Member",
        is_active=True,
    )
    comment = MagicMock(spec=Comment)
    comment.id = comment_id
    comment.organization_id = org_id
    comment.task_id = task_id
    comment.author_id = author_id

    regular_org_member = MagicMock(
        spec=OrganizationMember,
        organization_id=org_id,
        user_id=other_user_id,
        role=OrganizationRole.MEMBER,
    )
    task = MagicMock(spec=Task, id=task_id, project_id=project_id, organization_id=org_id)
    project = MagicMock(
        spec=Project,
        id=project_id,
        organization_id=org_id,
        visibility=ProjectVisibility.ORG_PUBLIC,
    )

    db = _setup_mock_db(comment, author, regular_org_member, task, project)
    service = CommentService(db)

    with pytest.raises(ForbiddenException) as exc_info:
        run_async(service.delete_comment(comment_id, user=other_user))
    assert exc_info.value.code == "NOT_COMMENT_AUTHOR"


def test_cross_tenant_comment_access_concealed() -> None:
    """Cross-tenant user cannot mutate or delete comments, returning 404 COMMENT_NOT_FOUND."""
    author_id = uuid.uuid4()
    cross_user_id = uuid.uuid4()
    org_id = uuid.uuid4()
    comment_id = uuid.uuid4()

    author = User(id=author_id, email="author@example.com", full_name="Author", is_active=True)
    cross_user = User(
        id=cross_user_id,
        email="foreign@example.com",
        full_name="Foreign Tenant",
        is_active=True,
    )
    comment = MagicMock(spec=Comment)
    comment.id = comment_id
    comment.organization_id = org_id
    comment.task_id = uuid.uuid4()
    comment.author_id = author_id

    # user_org_member is None for the comment's organization
    db = _setup_mock_db(comment, author, user_org_member=None)
    service = CommentService(db)

    with pytest.raises(NotFoundException) as exc_info_update:
        run_async(service.update_comment(comment_id, CommentUpdate(content="hack"), user=cross_user))
    assert exc_info_update.value.code == "COMMENT_NOT_FOUND"

    with pytest.raises(NotFoundException) as exc_info_delete:
        run_async(service.delete_comment(comment_id, user=cross_user))
    assert exc_info_delete.value.code == "COMMENT_NOT_FOUND"


def test_parent_resource_deleted_conceals_comment() -> None:
    """If the parent task or project is deleted, comment mutation returns 404 COMMENT_NOT_FOUND."""
    author_id = uuid.uuid4()
    org_id = uuid.uuid4()
    comment_id = uuid.uuid4()

    author = User(id=author_id, email="author@example.com", full_name="Author", is_active=True)
    comment = MagicMock(spec=Comment)
    comment.id = comment_id
    comment.organization_id = org_id
    comment.task_id = uuid.uuid4()
    comment.author_id = author_id

    org_member = MagicMock(
        spec=OrganizationMember,
        organization_id=org_id,
        user_id=author_id,
        role=OrganizationRole.MEMBER,
    )

    # task is None (deleted)
    db = _setup_mock_db(comment, author, org_member, task=None, project=None)
    service = CommentService(db)

    with pytest.raises(NotFoundException) as exc_info:
        run_async(service.update_comment(comment_id, CommentUpdate(content="test"), user=author))
    assert exc_info.value.code == "COMMENT_NOT_FOUND"


def test_restricted_project_non_member_conceals_comment() -> None:
    """In a RESTRICTED project, organization members who are not project members cannot access comments (404)."""
    author_id = uuid.uuid4()
    non_project_member_id = uuid.uuid4()
    org_id = uuid.uuid4()
    task_id = uuid.uuid4()
    project_id = uuid.uuid4()
    comment_id = uuid.uuid4()

    author = User(id=author_id, email="author@example.com", full_name="Author", is_active=True)
    non_project_member = User(
        id=non_project_member_id,
        email="orgmember@example.com",
        full_name="Org Member",
        is_active=True,
    )
    comment = MagicMock(spec=Comment)
    comment.id = comment_id
    comment.organization_id = org_id
    comment.task_id = task_id
    comment.author_id = author_id

    org_member = MagicMock(
        spec=OrganizationMember,
        organization_id=org_id,
        user_id=non_project_member_id,
        role=OrganizationRole.MEMBER,
    )
    task = MagicMock(spec=Task, id=task_id, project_id=project_id, organization_id=org_id)
    project = MagicMock(
        spec=Project,
        id=project_id,
        organization_id=org_id,
        visibility=ProjectVisibility.RESTRICTED,
    )

    # project_member is None -> User is not a member of this restricted project
    db = _setup_mock_db(
        comment,
        author,
        org_member,
        task=task,
        project=project,
        project_member=None,
    )
    service = CommentService(db)

    with pytest.raises(NotFoundException) as exc_info:
        run_async(service.update_comment(comment_id, CommentUpdate(content="test"), user=non_project_member))
    assert exc_info.value.code == "COMMENT_NOT_FOUND"


def test_restricted_project_member_can_edit_comment() -> None:
    """In a RESTRICTED project, an author who is a valid project member can update their comment."""
    author_id = uuid.uuid4()
    org_id = uuid.uuid4()
    task_id = uuid.uuid4()
    project_id = uuid.uuid4()
    comment_id = uuid.uuid4()

    author = User(id=author_id, email="author@example.com", full_name="Author", is_active=True)
    comment = MagicMock(spec=Comment)
    comment.id = comment_id
    comment.organization_id = org_id
    comment.task_id = task_id
    comment.author_id = author_id
    comment.author = author
    comment.content = "Restricted project comment"
    comment.created_at = "2026-10-11T00:00:00Z"
    comment.updated_at = "2026-10-11T00:00:00Z"

    org_member = MagicMock(
        spec=OrganizationMember,
        organization_id=org_id,
        user_id=author_id,
        role=OrganizationRole.MEMBER,
    )
    task = MagicMock(spec=Task, id=task_id, project_id=project_id, organization_id=org_id)
    project = MagicMock(
        spec=Project,
        id=project_id,
        organization_id=org_id,
        visibility=ProjectVisibility.RESTRICTED,
    )
    project_member = MagicMock(
        spec=ProjectMember,
        project_id=project_id,
        user_id=author_id,
        role=ProjectRole.MEMBER,
    )

    db = _setup_mock_db(
        comment,
        author,
        org_member,
        task=task,
        project=project,
        project_member=project_member,
    )
    service = CommentService(db)
    payload = CommentUpdate(content="Restricted project comment updated")

    updated_res = run_async(service.update_comment(comment_id, payload, user=author))
    assert updated_res.content == "Restricted project comment updated"
    assert comment.content == "Restricted project comment updated"
    assert db.commit.called


if __name__ == "__main__":
    test_comment_author_edit_success()
    test_former_member_cannot_update_historical_comment()
    test_former_member_cannot_delete_historical_comment()
    test_unauthorized_member_cannot_update_other_user_comment()
    test_admin_cannot_edit_other_user_comment()
    test_admin_can_delete_other_user_comment()
    test_regular_member_cannot_delete_other_user_comment()
    test_cross_tenant_comment_access_concealed()
    test_parent_resource_deleted_conceals_comment()
    test_restricted_project_non_member_conceals_comment()
    test_restricted_project_member_can_edit_comment()
    print("All 11 comment authorization tests passed successfully!")
