"""Comprehensive automated security regression test suite for TaskFlow.

Verifies remediation of Strix penetration test vulnerabilities:
1. VULN-0001: Deactivated/soft-deleted users cannot refresh tokens; session family revoked.
2. VULN-0002: Single-use refresh tokens: stale token replay immediately revokes session family.
3. VULN-0003: OWNER role cannot be invited via schema or service; peer-admin protection.
4. VULN-0004: Kanban cross-tenant BOLA / IDOR protection across boards, lists, tasks, moves,
   with strict HTTP 404 tenant concealment.
5. SQLAdmin session server-side revocation on logout.
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock

import pydantic
import pytest
from starlette.requests import Request
from starlette.responses import RedirectResponse

from app.admin.auth import TaskFlowAdminAuth
from app.core.base import utc_now
from app.core.dependencies import (
    get_accessible_board,
    get_accessible_list,
    get_accessible_task,
)
from app.core.exceptions import (
    BadRequestException,
    ForbiddenException,
    NotFoundException,
    UnauthorizedException,
)
from app.modules.auth.models import RefreshTokenSession
from app.modules.auth.service import AuthService
from app.modules.comments.schemas import CommentCreate
from app.modules.comments.service import CommentService
from app.modules.kanban.models import Board, List, Task
from app.modules.kanban.schemas import (
    BoardCreate,
    ListCreate,
    TaskCreate,
    TaskMoveRequest,
)
from app.modules.kanban.service import KanbanService
from app.modules.organizations.models import (
    OrganizationInvitation,
    OrganizationMember,
    OrganizationRole,
)
from app.modules.organizations.schemas import (
    InvitationCreate,
    MemberAddRequest,
)
from app.modules.organizations.service import OrganizationService
from app.modules.projects.models import (
    Project,
    ProjectVisibility,
)
from app.modules.users.models import User
from tests.utils import run_async

# ==============================================================================
# SECTION 1: VULN-0001 & VULN-0002 — Authentication & Refresh Token Security
# ==============================================================================


def test_vuln_0001_deactivated_user_refresh_token_revokes_family_and_raises_401() -> None:
    """VULN-0001: Inactive users cannot refresh tokens.

    When an inactive user presents a valid refresh token, the entire session
    family must be transactionally revoked and request rejected with ACCOUNT_INACTIVE.
    """
    db = AsyncMock()
    user_id = uuid.uuid4()
    family_id = uuid.uuid4()
    raw_token = "valid_looking_token_123"

    session_rec = MagicMock(spec=RefreshTokenSession)
    session_rec.id = uuid.uuid4()
    session_rec.user_id = user_id
    session_rec.session_family_id = family_id
    session_rec.is_revoked = False
    session_rec.replaced_by_id = None
    session_rec.expires_at = utc_now() + timedelta(days=30)

    # Inactive user in database
    deactivated_user = MagicMock(spec=User)
    deactivated_user.id = user_id
    deactivated_user.is_active = False  # DEACTIVATED
    deactivated_user.deleted_at = None

    res = MagicMock()
    res.scalar_one_or_none.side_effect = [session_rec, deactivated_user]
    db.execute.return_value = res

    service = AuthService(db)

    with pytest.raises(UnauthorizedException) as exc_info:
        run_async(
            service.rotate_refresh_token(
                raw_token=raw_token,
                operation_id=uuid.uuid4(),
            )
        )

    assert exc_info.value.code == "ACCOUNT_INACTIVE"
    assert db.execute.called
    assert db.commit.called


def test_vuln_0001_deleted_user_refresh_token_revokes_family_and_raises_401() -> None:
    """VULN-0001: Soft-deleted users cannot refresh tokens.

    When user record has deleted_at set or is absent, session family is revoked.
    """
    db = AsyncMock()
    user_id = uuid.uuid4()
    family_id = uuid.uuid4()
    raw_token = "valid_looking_token_deleted_user"

    session_rec = MagicMock(spec=RefreshTokenSession)
    session_rec.id = uuid.uuid4()
    session_rec.user_id = user_id
    session_rec.session_family_id = family_id
    session_rec.is_revoked = False
    session_rec.replaced_by_id = None

    # User lookup returns None because of deleted_at IS NULL filter
    res = MagicMock()
    res.scalar_one_or_none.side_effect = [session_rec, None]
    db.execute.return_value = res

    service = AuthService(db)

    with pytest.raises(UnauthorizedException) as exc_info:
        run_async(
            service.rotate_refresh_token(
                raw_token=raw_token,
                operation_id=uuid.uuid4(),
            )
        )

    assert exc_info.value.code == "ACCOUNT_INACTIVE"
    assert db.execute.called
    assert db.commit.called


def test_vuln_0002_stale_refresh_token_replay_immediately_revokes_family() -> None:
    """VULN-0002: Enforce single-use refresh tokens.

    Replay of any already-replaced token (replaced_by_id is not None) with an
    unrecognized operation ID must immediately revoke the entire session family
    without waiting for further generations.
    """
    db = AsyncMock()
    user_id = uuid.uuid4()
    family_id = uuid.uuid4()
    raw_token = "replayed_stale_token"

    session_rec = MagicMock(spec=RefreshTokenSession)
    session_rec.id = uuid.uuid4()
    session_rec.user_id = user_id
    session_rec.session_family_id = family_id
    session_rec.is_revoked = False
    session_rec.replaced_by_id = uuid.uuid4()  # ALREADY REPLACED

    active_user = MagicMock(spec=User)
    active_user.id = user_id
    active_user.is_active = True
    active_user.deleted_at = None

    # session_rec, active_user, op_record=None
    res = MagicMock()
    res.scalar_one_or_none.side_effect = [session_rec, active_user, None]
    db.execute.return_value = res

    service = AuthService(db)

    with pytest.raises(UnauthorizedException) as exc_info:
        run_async(
            service.rotate_refresh_token(
                raw_token=raw_token,
                operation_id=uuid.uuid4(),
            )
        )

    assert exc_info.value.code == "INVALID_REFRESH_TOKEN"
    assert db.execute.called
    assert db.commit.called


def test_sqladmin_server_side_session_revocation_on_logout() -> None:
    """SQLAdmin session revocation: Logged out sessions cannot be replayed."""
    auth = TaskFlowAdminAuth()
    session_id = str(uuid.uuid4())
    admin_id = uuid.uuid4()

    mock_request = MagicMock(spec=Request)
    mock_request.session = {
        "session_id": session_id,
        "admin_user_id": str(admin_id),
        "admin_email": "root@taskflow.dev",
        "is_superuser": True,
    }
    mock_request.url_for = MagicMock(return_value="/admin/login")

    # Perform logout
    logged_out = run_async(auth.logout(mock_request))
    assert logged_out is True
    assert len(mock_request.session) == 0

    # Attacker replays stolen signed cookie with the old session_id
    replayed_request = MagicMock(spec=Request)
    replayed_request.session = {
        "session_id": session_id,
        "admin_user_id": str(admin_id),
        "admin_email": "root@taskflow.dev",
        "is_superuser": True,
    }
    replayed_request.url_for = MagicMock(return_value="/admin/login")

    result = run_async(auth.authenticate(replayed_request))
    assert isinstance(result, RedirectResponse)
    assert result.status_code == 302
    assert len(replayed_request.session) == 0  # Replayed session destroyed


# ==============================================================================
# SECTION 2: VULN-0003 — Organization Role Escalation & Peer-Admin Protection
# ==============================================================================


def test_vuln_0003_pydantic_schema_rejects_owner_invitation() -> None:
    """VULN-0003: InvitationCreate and MemberAddRequest reject OWNER role at schema level."""
    with pytest.raises(pydantic.ValidationError) as exc_info:
        InvitationCreate(email="victim@example.com", role=OrganizationRole.OWNER)
    assert "Cannot invite member with OWNER role" in str(exc_info.value)

    with pytest.raises(pydantic.ValidationError) as exc_info2:
        MemberAddRequest(email="victim@example.com", role=OrganizationRole.OWNER)
    assert "Cannot assign OWNER role directly" in str(exc_info2.value)


def test_vuln_0003_service_create_invitation_rejects_owner_role() -> None:
    """VULN-0003: Service level create_invitation strictly rejects OWNER role."""
    db = AsyncMock()
    service = OrganizationService(db)
    org_id = uuid.uuid4()
    actor = MagicMock(spec=User)
    actor.id = uuid.uuid4()

    # Create mock payload bypassing pydantic validation
    payload = MagicMock(spec=InvitationCreate)
    payload.role = OrganizationRole.OWNER
    payload.email = "evil@example.com"

    with pytest.raises(BadRequestException) as exc_info:
        run_async(service.create_invitation(org_id, payload, actor))

    assert exc_info.value.code == "INVALID_ROLE_ASSIGNMENT"


def test_vuln_0003_service_accept_invitation_defense_in_depth_rejects_owner() -> None:
    """VULN-0003: Defense-in-depth: accept_invitation refuses to grant OWNER role."""
    db = AsyncMock()
    inv = MagicMock(spec=OrganizationInvitation)
    inv.id = uuid.uuid4()
    inv.organization_id = uuid.uuid4()
    inv.email = "target@example.com"
    inv.role = OrganizationRole.OWNER  # Tampered or legacy record
    inv.accepted_at = None
    inv.revoked_at = None
    inv.expired_at = None
    inv.expires_at = utc_now() + timedelta(days=5)

    db.execute.return_value = MagicMock(scalar_one_or_none=MagicMock(return_value=inv))
    service = OrganizationService(db)

    user = MagicMock(spec=User)
    user.id = uuid.uuid4()
    user.email = "target@example.com"

    with pytest.raises(ForbiddenException) as exc_info:
        run_async(service.accept_invitation("secret_token", user))

    assert exc_info.value.code == "INVALID_ROLE_ASSIGNMENT"


def test_peer_admin_cannot_demote_or_modify_peer_admin() -> None:
    """RBAC Invariant: Only organization OWNER can modify an ADMIN role.

    An organization ADMIN cannot demote, promote, or change the role of another ADMIN.
    """
    db = AsyncMock()
    org_id = uuid.uuid4()
    target_user_id = uuid.uuid4()

    target_member = MagicMock(spec=OrganizationMember)
    target_member.organization_id = org_id
    target_member.user_id = target_user_id
    target_member.role = OrganizationRole.ADMIN  # TARGET IS ADMIN

    user = MagicMock(spec=User)
    db.execute.return_value = MagicMock(one_or_none=MagicMock(return_value=(target_member, user)))
    service = OrganizationService(db)

    # Actor role is ADMIN (not OWNER)
    with pytest.raises(ForbiddenException) as exc_info:
        run_async(
            service.update_member_role(
                organization_id=org_id,
                user_id=target_user_id,
                new_role=OrganizationRole.MEMBER,
                actor_role="ADMIN",  # Peer admin attempt
            )
        )

    assert exc_info.value.code == "INSUFFICIENT_PERMISSIONS"


def test_owner_can_modify_admin_role() -> None:
    """RBAC: Organization OWNER can modify an ADMIN's role."""
    db = AsyncMock()
    org_id = uuid.uuid4()
    target_user_id = uuid.uuid4()

    target_member = MagicMock(spec=OrganizationMember)
    target_member.id = uuid.uuid4()
    target_member.organization_id = org_id
    target_member.user_id = target_user_id
    target_member.role = OrganizationRole.ADMIN
    target_member.created_at = utc_now()
    target_member.updated_at = utc_now()

    user = MagicMock(spec=User)
    user.id = target_user_id
    user.email = "admin@example.com"
    user.full_name = "Admin"
    user.avatar_url = None

    db.execute.return_value = MagicMock(one_or_none=MagicMock(return_value=(target_member, user)))
    service = OrganizationService(db)

    run_async(
        service.update_member_role(
            organization_id=org_id,
            user_id=target_user_id,
            new_role=OrganizationRole.MEMBER,
            actor_role="OWNER",  # Legit OWNER actor
        )
    )

    assert target_member.role == OrganizationRole.MEMBER
    assert db.commit.called


# ==============================================================================
# SECTION 3: VULN-0004 — Cross-Tenant BOLA / IDOR & 404 Concealment
# ==============================================================================


def test_vuln_0004_board_access_foreign_tenant_concealed_with_404() -> None:
    """VULN-0004: Board lookup from foreign tenant raises 404 BOARD_NOT_FOUND."""
    db = AsyncMock()
    board_id = uuid.uuid4()
    user_tenant_a = MagicMock(spec=User)
    user_tenant_a.id = uuid.uuid4()

    board_tenant_b = MagicMock(spec=Board)
    board_tenant_b.id = board_id
    board_tenant_b.project_id = uuid.uuid4()

    project_tenant_b = MagicMock(spec=Project)
    project_tenant_b.id = board_tenant_b.project_id
    project_tenant_b.organization_id = uuid.uuid4()  # Tenant B
    project_tenant_b.visibility = ProjectVisibility.ORG_PUBLIC

    # 1. Join query returns board and project
    # 2. Org membership lookup for user in Tenant B returns None!
    exec_mock = MagicMock()
    exec_mock.one_or_none.return_value = (board_tenant_b, project_tenant_b)
    exec_mock.scalar_one_or_none.return_value = None  # NOT IN TENANT B
    db.execute.return_value = exec_mock

    with pytest.raises(NotFoundException) as exc_info:
        run_async(get_accessible_board(board_id, user_tenant_a, db, min_role="VIEWER"))

    assert exc_info.value.code == "BOARD_NOT_FOUND"
    assert exc_info.value.status_code == 404


def test_vuln_0004_list_access_foreign_tenant_concealed_with_404() -> None:
    """VULN-0004: List lookup from foreign tenant raises 404 LIST_NOT_FOUND."""
    db = AsyncMock()
    list_id = uuid.uuid4()
    user_tenant_a = MagicMock(spec=User)
    user_tenant_a.id = uuid.uuid4()

    lst_tenant_b = MagicMock(spec=List)
    lst_tenant_b.id = list_id
    lst_tenant_b.project_id = uuid.uuid4()

    project_tenant_b = MagicMock(spec=Project)
    project_tenant_b.id = lst_tenant_b.project_id
    project_tenant_b.organization_id = uuid.uuid4()  # Tenant B
    project_tenant_b.visibility = ProjectVisibility.ORG_PUBLIC

    exec_mock = MagicMock()
    exec_mock.one_or_none.return_value = (lst_tenant_b, project_tenant_b)
    exec_mock.scalar_one_or_none.return_value = None  # NOT IN TENANT B
    db.execute.return_value = exec_mock

    with pytest.raises(NotFoundException) as exc_info:
        run_async(get_accessible_list(list_id, user_tenant_a, db, min_role="VIEWER"))

    assert exc_info.value.code == "LIST_NOT_FOUND"
    assert exc_info.value.status_code == 404


def test_vuln_0004_task_access_foreign_tenant_concealed_with_404() -> None:
    """VULN-0004: Task lookup from foreign tenant raises 404 TASK_NOT_FOUND."""
    db = AsyncMock()
    task_id = uuid.uuid4()
    user_tenant_a = MagicMock(spec=User)
    user_tenant_a.id = uuid.uuid4()

    task_tenant_b = MagicMock(spec=Task)
    task_tenant_b.id = task_id
    task_tenant_b.project_id = uuid.uuid4()

    project_tenant_b = MagicMock(spec=Project)
    project_tenant_b.id = task_tenant_b.project_id
    project_tenant_b.organization_id = uuid.uuid4()  # Tenant B
    project_tenant_b.visibility = ProjectVisibility.ORG_PUBLIC

    exec_mock = MagicMock()
    exec_mock.one_or_none.return_value = (task_tenant_b, project_tenant_b)
    exec_mock.scalar_one_or_none.return_value = None  # NOT IN TENANT B
    db.execute.return_value = exec_mock

    with pytest.raises(NotFoundException) as exc_info:
        run_async(get_accessible_task(task_id, user_tenant_a, db, min_role="VIEWER"))

    assert exc_info.value.code == "TASK_NOT_FOUND"
    assert exc_info.value.status_code == 404


def test_vuln_0004_restricted_project_access_concealed_with_404() -> None:
    """VULN-0004: Restricted project without project membership returns 404."""
    db = AsyncMock()
    task_id = uuid.uuid4()
    user = MagicMock(spec=User)
    user.id = uuid.uuid4()

    org_id = uuid.uuid4()
    task = MagicMock(spec=Task)
    task.id = task_id
    task.project_id = uuid.uuid4()

    project = MagicMock(spec=Project)
    project.id = task.project_id
    project.organization_id = org_id
    project.visibility = ProjectVisibility.RESTRICTED  # RESTRICTED VISIBILITY

    # Org member exists with ordinary MEMBER role
    org_member = MagicMock(spec=OrganizationMember)
    org_member.role = "MEMBER"

    # Project member query returns None!
    exec_mock = MagicMock()
    exec_mock.one_or_none.return_value = (task, project)
    exec_mock.scalar_one_or_none.side_effect = [org_member, None]
    db.execute.return_value = exec_mock

    with pytest.raises(NotFoundException) as exc_info:
        run_async(get_accessible_task(task_id, user, db, min_role="VIEWER"))

    assert exc_info.value.code == "TASK_NOT_FOUND"
    assert exc_info.value.status_code == 404


def test_vuln_0004_kanban_service_create_board_cross_tenant_rejected() -> None:
    """VULN-0004: create_board returns 404 on cross-tenant probe."""
    db = AsyncMock()
    foreign_project_id = uuid.uuid4()
    user = MagicMock(spec=User)
    user.id = uuid.uuid4()

    # Project query returns None (or inaccessible)
    db.execute.return_value = MagicMock(scalar_one_or_none=MagicMock(return_value=None))
    service = KanbanService(db)

    payload = BoardCreate(name="Malicious Board")

    with pytest.raises(NotFoundException) as exc_info:
        run_async(service.create_board(foreign_project_id, payload, creator=user))

    assert exc_info.value.code == "PROJECT_NOT_FOUND"


def test_vuln_0004_kanban_service_create_list_cross_tenant_rejected() -> None:
    """VULN-0004: create_list validates board accessibility and returns 404 on foreign board."""
    db = AsyncMock()
    foreign_board_id = uuid.uuid4()
    user = MagicMock(spec=User)
    user.id = uuid.uuid4()

    db.execute.return_value = MagicMock(one_or_none=MagicMock(return_value=None))
    service = KanbanService(db)

    payload = ListCreate(name="Injected List")

    with pytest.raises(NotFoundException) as exc_info:
        run_async(service.create_list(foreign_board_id, payload, creator=user))

    assert exc_info.value.code == "BOARD_NOT_FOUND"


def test_vuln_0004_kanban_service_create_task_cross_tenant_rejected() -> None:
    """VULN-0004: create_task validates list accessibility and returns 404 on foreign list."""
    db = AsyncMock()
    foreign_list_id = uuid.uuid4()
    user = MagicMock(spec=User)
    user.id = uuid.uuid4()

    db.execute.return_value = MagicMock(one_or_none=MagicMock(return_value=None))
    service = KanbanService(db)

    payload = TaskCreate(title="Injected Task")

    with pytest.raises(NotFoundException) as exc_info:
        run_async(service.create_task(foreign_list_id, payload, creator=user))

    assert exc_info.value.code == "LIST_NOT_FOUND"


def test_vuln_0004_kanban_service_move_task_cross_tenant_source_rejected() -> None:
    """VULN-0004: move_task rejects foreign task with 404 TASK_NOT_FOUND."""
    db = AsyncMock()
    foreign_task_id = uuid.uuid4()
    user = MagicMock(spec=User)
    user.id = uuid.uuid4()

    db.execute.return_value = MagicMock(one_or_none=MagicMock(return_value=None))
    service = KanbanService(db)

    payload = TaskMoveRequest(
        target_list_id=uuid.uuid4(),
        expected_version=1,
    )

    with pytest.raises(NotFoundException) as exc_info:
        run_async(service.move_task(foreign_task_id, payload, user=user))

    assert exc_info.value.code == "TASK_NOT_FOUND"


def test_vuln_0004_kanban_service_move_task_cross_tenant_target_list_rejected() -> None:
    """VULN-0004: move_task rejects moving task to a target list on another tenant/board."""
    db = AsyncMock()
    task_id = uuid.uuid4()
    source_list_id = uuid.uuid4()
    board_id = uuid.uuid4()
    foreign_target_list_id = uuid.uuid4()

    user = MagicMock(spec=User)
    user.id = uuid.uuid4()

    project = MagicMock(spec=Project)
    project.id = uuid.uuid4()
    project.organization_id = uuid.uuid4()
    project.visibility = ProjectVisibility.ORG_PUBLIC

    task = MagicMock(spec=Task)
    task.id = task_id
    task.project_id = project.id
    task.list_id = source_list_id
    task.board_id = board_id
    task.version = 1

    org_member = MagicMock(spec=OrganizationMember)
    org_member.role = "MEMBER"

    # get_accessible_task succeeds for source, but get_accessible_list fails for foreign target
    exec_mock = MagicMock()
    # 1. get_accessible_task -> (task, project)
    # 2. check_project_access -> org_member
    # 3. get_accessible_list -> None (cross-tenant target list)
    exec_mock.one_or_none.side_effect = [(task, project), None]
    exec_mock.scalar_one_or_none.return_value = org_member
    db.execute.return_value = exec_mock

    service = KanbanService(db)
    payload = TaskMoveRequest(
        target_list_id=foreign_target_list_id,
        expected_version=1,
    )

    with pytest.raises(NotFoundException) as exc_info:
        run_async(service.move_task(task_id, payload, user=user))

    assert exc_info.value.code == "LIST_NOT_FOUND"


def test_vuln_0004_kanban_service_delete_task_cross_tenant_rejected() -> None:
    """VULN-0004: delete_task validates task accessibility and rejects foreign task."""
    db = AsyncMock()
    foreign_task_id = uuid.uuid4()
    user = MagicMock(spec=User)
    user.id = uuid.uuid4()

    db.execute.return_value = MagicMock(one_or_none=MagicMock(return_value=None))
    service = KanbanService(db)

    with pytest.raises(NotFoundException) as exc_info:
        run_async(service.delete_task(foreign_task_id, user=user))

    assert exc_info.value.code == "TASK_NOT_FOUND"


# ==============================================================================
# SECTION 4: Comments Subsystem Authorization
# ==============================================================================


def test_create_comment_cross_tenant_task_returns_404() -> None:
    """Cross-tenant comment creation is rejected with 404 TASK_NOT_FOUND."""
    db = AsyncMock()
    foreign_task_id = uuid.uuid4()
    user = MagicMock(spec=User)
    user.id = uuid.uuid4()

    db.execute.return_value = MagicMock(one_or_none=MagicMock(return_value=None))
    service = CommentService(db)

    payload = CommentCreate(content="Malicious comment injection")

    with pytest.raises(NotFoundException) as exc_info:
        run_async(service.create_comment(foreign_task_id, payload, author=user))

    assert exc_info.value.code == "TASK_NOT_FOUND"


def test_list_comments_cross_tenant_task_returns_404() -> None:
    """Cross-tenant comment listing is rejected with 404 TASK_NOT_FOUND."""
    db = AsyncMock()
    foreign_task_id = uuid.uuid4()
    user = MagicMock(spec=User)
    user.id = uuid.uuid4()

    db.execute.return_value = MagicMock(one_or_none=MagicMock(return_value=None))
    service = CommentService(db)

    with pytest.raises(NotFoundException) as exc_info:
        run_async(service.list_comments(foreign_task_id, user=user))

    assert exc_info.value.code == "TASK_NOT_FOUND"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
