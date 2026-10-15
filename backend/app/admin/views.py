"""SQLAdmin ModelView definitions for TaskFlow domain entities."""

from sqladmin import ModelView

from app.modules.audit_logs.models import AuditLog
from app.modules.auth.models import RefreshTokenSession
from app.modules.comments.models import Comment
from app.modules.kanban.models import Board, List, Task
from app.modules.notifications.models import Notification
from app.modules.organizations.models import (
    Organization,
    OrganizationInvitation,
    OrganizationMember,
)
from app.modules.projects.models import Project, ProjectMember
from app.modules.users.models import User


class UserAdmin(ModelView, model=User):
    """Administration view for user accounts."""

    name = "User"
    name_plural = "Users"
    icon = "fa-solid fa-users"

    column_list = [
        User.id,
        User.email,
        User.full_name,
        User.is_active,
        User.is_superuser,
        User.created_at,
        User.deleted_at,
    ]
    column_details_exclude_list = [User.hashed_password]
    form_excluded_columns = [
        User.hashed_password,
        User.created_at,
        User.updated_at,
        User.deleted_at,
    ]
    column_searchable_list = [User.email, User.full_name]
    column_sortable_list = [
        User.email,
        User.full_name,
        User.created_at,
        User.is_active,
        User.is_superuser,
    ]

    can_create = False  # Account creation requires password hashing through auth service or CLI
    can_delete = False  # Direct hard delete breaks foreign-key integrity; deactivate via is_active
    can_edit = True


class OrganizationAdmin(ModelView, model=Organization):
    """Administration view for tenant organizations (workspaces)."""

    name = "Organization"
    name_plural = "Organizations"
    icon = "fa-solid fa-building"

    column_list = [
        Organization.id,
        Organization.name,
        Organization.slug,
        Organization.is_archived,
        Organization.created_at,
        Organization.deleted_at,
    ]
    column_searchable_list = [Organization.name, Organization.slug]
    column_sortable_list = [
        Organization.name,
        Organization.slug,
        Organization.created_at,
        Organization.is_archived,
    ]

    can_create = False  # Organization creation requires tenant initialization with an OWNER
    can_delete = False  # Cascading tenant destruction must not be performed via generic CRUD
    can_edit = True


class OrganizationMemberAdmin(ModelView, model=OrganizationMember):
    """Administration view for workspace role memberships."""

    name = "Organization Member"
    name_plural = "Organization Members"
    icon = "fa-solid fa-id-badge"

    column_list = [
        OrganizationMember.id,
        OrganizationMember.organization_id,
        OrganizationMember.user_id,
        OrganizationMember.role,
        OrganizationMember.created_at,
    ]
    column_sortable_list = [OrganizationMember.role, OrganizationMember.created_at]

    can_create = False  # Memberships must be established through invitation/onboarding flows
    can_delete = False  # Member deletion requires atomic task unassignment across the tenant
    can_edit = True


class OrganizationInvitationAdmin(ModelView, model=OrganizationInvitation):
    """Administration view for workspace invitations."""

    name = "Organization Invitation"
    name_plural = "Organization Invitations"
    icon = "fa-solid fa-envelope"

    column_list = [
        OrganizationInvitation.id,
        OrganizationInvitation.organization_id,
        OrganizationInvitation.email,
        OrganizationInvitation.role,
        OrganizationInvitation.expires_at,
        OrganizationInvitation.accepted_at,
        OrganizationInvitation.revoked_at,
        OrganizationInvitation.created_at,
    ]
    column_details_exclude_list = [OrganizationInvitation.token_hash]
    column_searchable_list = [OrganizationInvitation.email]
    column_sortable_list = [OrganizationInvitation.expires_at, OrganizationInvitation.created_at]

    can_create = False
    can_edit = False
    can_delete = False  # Read-only audit view of invitation lifecycle


class ProjectAdmin(ModelView, model=Project):
    """Administration view for workspace projects."""

    name = "Project"
    name_plural = "Projects"
    icon = "fa-solid fa-folder"

    column_list = [
        Project.id,
        Project.organization_id,
        Project.name,
        Project.key,
        Project.visibility,
        Project.is_archived,
        Project.created_at,
        Project.deleted_at,
    ]
    column_searchable_list = [Project.name, Project.key]
    column_sortable_list = [Project.name, Project.key, Project.created_at]

    can_create = False  # Projects should be provisioned with proper creator attribution
    can_delete = False  # Soft delete via project service
    can_edit = True


class ProjectMemberAdmin(ModelView, model=ProjectMember):
    """Administration view for restricted project member assignments."""

    name = "Project Member"
    name_plural = "Project Members"
    icon = "fa-solid fa-user-tag"

    column_list = [
        ProjectMember.id,
        ProjectMember.project_id,
        ProjectMember.user_id,
        ProjectMember.project_role,
        ProjectMember.created_at,
    ]
    column_sortable_list = [ProjectMember.project_role, ProjectMember.created_at]

    can_create = False
    can_delete = True
    can_edit = True


class BoardAdmin(ModelView, model=Board):
    """Administration view for Kanban boards."""

    name = "Board"
    name_plural = "Boards"
    icon = "fa-solid fa-table-columns"

    column_list = [
        Board.id,
        Board.project_id,
        Board.organization_id,
        Board.name,
        Board.created_at,
        Board.deleted_at,
    ]
    column_searchable_list = [Board.name]
    column_sortable_list = [Board.name, Board.created_at]

    can_create = False  # Board creation initializes default lists
    can_delete = False
    can_edit = True


class ListAdmin(ModelView, model=List):
    """Administration view for Kanban workflow columns."""

    name = "List Column"
    name_plural = "List Columns"
    icon = "fa-solid fa-list"

    column_list = [
        List.id,
        List.board_id,
        List.name,
        List.ordering_key,
        List.version,
        List.created_at,
        List.deleted_at,
    ]
    column_searchable_list = [List.name]
    column_sortable_list = [List.name, List.version, List.created_at]

    can_create = False  # Lists require LexoRank midpoint calculations
    can_edit = False  # Editing version or ordering_key breaks OCC invariants
    can_delete = False


class TaskAdmin(ModelView, model=Task):
    """Administration view for Kanban tasks."""

    name = "Task"
    name_plural = "Tasks"
    icon = "fa-solid fa-check-double"

    column_list = [
        Task.id,
        Task.title,
        Task.priority,
        Task.list_id,
        Task.project_id,
        Task.assignee_id,
        Task.version,
        Task.due_date,
        Task.completed_at,
        Task.created_at,
        Task.deleted_at,
    ]
    column_searchable_list = [Task.title]
    column_sortable_list = [Task.title, Task.priority, Task.created_at, Task.due_date]

    form_excluded_columns = [
        Task.ordering_key,
        Task.version,
        Task.created_at,
        Task.updated_at,
        Task.deleted_at,
    ]

    can_create = False  # Task creation requires container list locking and LexoRank assignment
    can_delete = False  # Direct hard deletion breaks comments and notifications
    can_edit = True  # Can update title, description, priority, assignee


class CommentAdmin(ModelView, model=Comment):
    """Administration view for task discussion comments."""

    name = "Comment"
    name_plural = "Comments"
    icon = "fa-solid fa-comments"

    column_list = [
        Comment.id,
        Comment.task_id,
        Comment.author_id,
        Comment.content,
        Comment.created_at,
        Comment.deleted_at,
    ]
    column_searchable_list = [Comment.content]
    column_sortable_list = [Comment.created_at]

    can_create = False
    can_edit = False
    can_delete = False


class NotificationAdmin(ModelView, model=Notification):
    """Administration view for user notifications."""

    name = "Notification"
    name_plural = "Notifications"
    icon = "fa-solid fa-bell"

    column_list = [
        Notification.id,
        Notification.user_id,
        Notification.event_type,
        Notification.title,
        Notification.is_read,
        Notification.created_at,
    ]
    column_searchable_list = [Notification.title]
    column_sortable_list = [Notification.created_at, Notification.is_read]

    can_create = False
    can_edit = False
    can_delete = False


class AuditLogAdmin(ModelView, model=AuditLog):
    """Administration view for immutable audit logs."""

    name = "Audit Log"
    name_plural = "Audit Logs"
    icon = "fa-solid fa-shield-halved"

    column_list = [
        AuditLog.id,
        AuditLog.organization_id,
        AuditLog.actor_id,
        AuditLog.action,
        AuditLog.target_type,
        AuditLog.target_id,
        AuditLog.ip_address,
        AuditLog.created_at,
    ]
    column_searchable_list = [AuditLog.action, AuditLog.ip_address]
    column_sortable_list = [AuditLog.created_at, AuditLog.action]

    can_create = False  # STRICTLY IMMUTABLE
    can_edit = False  # STRICTLY IMMUTABLE
    can_delete = False  # STRICTLY IMMUTABLE


class RefreshTokenSessionAdmin(ModelView, model=RefreshTokenSession):
    """Administration view for refresh token sessions."""

    name = "Refresh Token Session"
    name_plural = "Refresh Token Sessions"
    icon = "fa-solid fa-key"

    column_list = [
        RefreshTokenSession.id,
        RefreshTokenSession.user_id,
        RefreshTokenSession.session_family_id,
        RefreshTokenSession.is_revoked,
        RefreshTokenSession.expires_at,
        RefreshTokenSession.ip_address,
        RefreshTokenSession.created_at,
    ]
    column_details_exclude_list = [RefreshTokenSession.token_hash]
    form_excluded_columns = [
        RefreshTokenSession.token_hash,
        RefreshTokenSession.created_at,
    ]
    column_sortable_list = [RefreshTokenSession.created_at, RefreshTokenSession.expires_at]

    can_create = False
    can_delete = False
    can_edit = True  # Can revoke compromised sessions manually by setting is_revoked = True


ALL_ADMIN_VIEWS = [
    UserAdmin,
    OrganizationAdmin,
    OrganizationMemberAdmin,
    OrganizationInvitationAdmin,
    ProjectAdmin,
    ProjectMemberAdmin,
    BoardAdmin,
    ListAdmin,
    TaskAdmin,
    CommentAdmin,
    NotificationAdmin,
    AuditLogAdmin,
    RefreshTokenSessionAdmin,
]
