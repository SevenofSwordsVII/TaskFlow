"""Automated Route Inventory and Coverage Verification for TaskFlow.

Inspects all registered FastAPI endpoints and ensures every route has an
explicit disposition and coverage strategy in the Locust load test suite.
"""

import sys
from typing import NamedTuple

from app.main import app


class RouteItem(NamedTuple):
    method: str
    path: str
    endpoint: str


def discover_fastapi_routes() -> list[RouteItem]:
    """Extract all registered HTTP routes from the FastAPI application."""
    routes: list[RouteItem] = []
    for route in app.routes:
        # Check standard Route objects
        if hasattr(route, "methods") and hasattr(route, "path"):
            for method in sorted(route.methods):
                if method in ("GET", "POST", "PUT", "PATCH", "DELETE"):
                    routes.append(
                        RouteItem(
                            method=method,
                            path=route.path,
                            endpoint=route.endpoint.__name__,
                        )
                    )
    return sorted(routes, key=lambda r: (r.path, r.method))


# Canonical route inventory map: (Method, Path) -> (Module, Category, Disposition)
ROUTE_DISPOSITION_MAP = {
    # Health & System
    ("GET", "/health"): (
        "system",
        "Normal Load-Test",
        "Covered in AnonymousUser.check_health",
    ),
    # Auth
    ("POST", "/api/v1/auth/register"): (
        "auth",
        "Normal Load-Test",
        "Covered in AuthenticatedBaseUser.on_start",
    ),
    ("POST", "/api/v1/auth/token"): (
        "auth",
        "Normal Load-Test",
        "Covered in AuthenticatedBaseUser.on_start",
    ),
    ("POST", "/api/v1/auth/refresh"): (
        "auth",
        "Normal Load-Test",
        "Covered in KanbanStandardUser.token_refresh_flow",
    ),
    ("POST", "/api/v1/auth/logout"): (
        "auth",
        "Normal Load-Test",
        "Covered in AuthenticatedBaseUser.on_stop",
    ),
    ("GET", "/api/v1/auth/me"): (
        "auth",
        "Normal Load-Test",
        "Covered in AuthenticatedBaseUser.setup_test_workspace",
    ),
    # Users
    ("GET", "/api/v1/users/me"): (
        "users",
        "Normal Load-Test",
        "Covered in KanbanStandardUser.user_profile_workflow",
    ),
    ("PATCH", "/api/v1/users/me"): (
        "users",
        "Normal Load-Test",
        "Covered in KanbanStandardUser.user_profile_workflow",
    ),
    ("DELETE", "/api/v1/users/me"): (
        "users",
        "Specialized Security / Lifecycle",
        "Covered in dedicated user deletion lifecycle scenario",
    ),
    # Organizations
    ("POST", "/api/v1/organizations"): (
        "organizations",
        "Normal Load-Test",
        "Covered in AuthenticatedBaseUser.setup_test_workspace",
    ),
    ("GET", "/api/v1/organizations"): (
        "organizations",
        "Normal Load-Test",
        "Covered in AuthenticatedBaseUser.setup_test_workspace",
    ),
    ("POST", "/api/v1/organizations/invitations/accept"): (
        "organizations",
        "Normal Load-Test",
        "Covered in member onboarding workflow with valid token",
    ),
    ("GET", "/api/v1/organizations/{organization_id}/members"): (
        "organizations",
        "Normal Load-Test",
        "Covered in OrgAdminUser.manage_organization_members",
    ),
    ("PATCH", "/api/v1/organizations/{organization_id}/members/{user_id}"): (
        "organizations",
        "Normal Load-Test",
        "Covered in administrative member role update workflow",
    ),
    ("DELETE", "/api/v1/organizations/{organization_id}/members/{user_id}"): (
        "organizations",
        "Specialized Security / Lifecycle",
        "Covered in member offboarding test (removes test member)",
    ),
    ("POST", "/api/v1/organizations/{organization_id}/transfer-ownership"): (
        "organizations",
        "Specialized Security / Lifecycle",
        "Covered in dedicated ownership transfer scenario",
    ),
    ("POST", "/api/v1/organizations/{organization_id}/invitations"): (
        "organizations",
        "Normal Load-Test",
        "Covered in OrgAdminUser.invitations_lifecycle",
    ),
    ("GET", "/api/v1/organizations/{organization_id}/invitations"): (
        "organizations",
        "Normal Load-Test",
        "Covered in OrgAdminUser.invitations_lifecycle",
    ),
    ("DELETE", "/api/v1/organizations/{organization_id}/invitations/{invitation_id}"): (
        "organizations",
        "Normal Load-Test",
        "Covered in OrgAdminUser.invitations_lifecycle",
    ),
    # Projects
    ("POST", "/api/v1/organizations/{organization_id}/projects"): (
        "projects",
        "Normal Load-Test",
        "Covered in AuthenticatedBaseUser.setup_test_workspace",
    ),
    ("GET", "/api/v1/organizations/{organization_id}/projects"): (
        "projects",
        "Normal Load-Test",
        "Covered in AuthenticatedBaseUser.setup_test_workspace",
    ),
    ("GET", "/api/v1/projects/{project_id}"): (
        "projects",
        "Normal Load-Test",
        "Covered in OrgAdminUser.project_and_members_management",
    ),
    ("PATCH", "/api/v1/projects/{project_id}"): (
        "projects",
        "Normal Load-Test",
        "Covered in OrgAdminUser.project_and_members_management",
    ),
    ("DELETE", "/api/v1/projects/{project_id}"): (
        "projects",
        "Specialized Security / Lifecycle",
        "Covered in project teardown lifecycle",
    ),
    ("GET", "/api/v1/projects/{project_id}/members"): (
        "projects",
        "Normal Load-Test",
        "Covered in OrgAdminUser.project_and_members_management",
    ),
    ("POST", "/api/v1/projects/{project_id}/members"): (
        "projects",
        "Normal Load-Test",
        "Covered in project member assignment workflow",
    ),
    ("DELETE", "/api/v1/projects/{project_id}/members/{user_id}"): (
        "projects",
        "Specialized Security / Lifecycle",
        "Covered in project member unassignment workflow",
    ),
    # Kanban
    ("POST", "/api/v1/projects/{project_id}/boards"): (
        "kanban",
        "Normal Load-Test",
        "Covered in AuthenticatedBaseUser.setup_test_workspace",
    ),
    ("GET", "/api/v1/boards/{board_id}"): (
        "kanban",
        "Normal Load-Test",
        "Covered in KanbanStandardUser.view_board_tree",
    ),
    ("POST", "/api/v1/boards/{board_id}/lists"): (
        "kanban",
        "Normal Load-Test",
        "Covered in AuthenticatedBaseUser.setup_test_workspace",
    ),
    ("POST", "/api/v1/lists/{list_id}/move"): (
        "kanban",
        "Normal Load-Test",
        "Covered in OrgAdminUser.reorder_list_occ",
    ),
    ("POST", "/api/v1/lists/{list_id}/tasks"): (
        "kanban",
        "Normal Load-Test",
        "Covered in KanbanStandardUser.task_lifecycle_and_mutation",
    ),
    ("PATCH", "/api/v1/tasks/{task_id}"): (
        "kanban",
        "Normal Load-Test",
        "Covered in KanbanStandardUser.task_lifecycle_and_mutation",
    ),
    ("POST", "/api/v1/tasks/{task_id}/move"): (
        "kanban",
        "Normal Load-Test",
        "Covered in KanbanStandardUser.move_task_occ",
    ),
    ("DELETE", "/api/v1/tasks/{task_id}"): (
        "kanban",
        "Normal Load-Test",
        "Covered in KanbanStandardUser.task_lifecycle_and_mutation",
    ),
    # Comments
    ("POST", "/api/v1/tasks/{task_id}/comments"): (
        "comments",
        "Normal Load-Test",
        "Covered in KanbanStandardUser.comment_lifecycle",
    ),
    ("GET", "/api/v1/tasks/{task_id}/comments"): (
        "comments",
        "Normal Load-Test",
        "Covered in KanbanStandardUser.comment_lifecycle",
    ),
    ("PATCH", "/api/v1/comments/{comment_id}"): (
        "comments",
        "Normal Load-Test",
        "Covered in KanbanStandardUser.comment_lifecycle",
    ),
    ("DELETE", "/api/v1/comments/{comment_id}"): (
        "comments",
        "Normal Load-Test",
        "Covered in KanbanStandardUser.comment_lifecycle",
    ),
    # Notifications
    ("GET", "/api/v1/notifications"): (
        "notifications",
        "Normal Load-Test",
        "Covered in KanbanStandardUser.notifications_inbox",
    ),
    ("PATCH", "/api/v1/notifications/{notification_id}/read"): (
        "notifications",
        "Normal Load-Test",
        "Covered in KanbanStandardUser.notifications_inbox",
    ),
    ("POST", "/api/v1/notifications/mark-all-read"): (
        "notifications",
        "Normal Load-Test",
        "Covered in KanbanStandardUser.notifications_inbox",
    ),
    # Audit Logs
    ("GET", "/api/v1/organizations/{organization_id}/audit-logs"): (
        "audit_logs",
        "Normal Load-Test",
        "Covered in OrgAdminUser.manage_organization_members",
    ),
}


def verify_route_inventory() -> int:
    """Validate that every registered FastAPI route matches the route inventory."""
    registered = discover_fastapi_routes()
    missing_disposition = []

    print(f"Total FastAPI Routes Discovered: {len(registered)}")
    print("-" * 75)

    for r in registered:
        key = (r.method, r.path)
        if key in ROUTE_DISPOSITION_MAP:
            mod, cat, disp = ROUTE_DISPOSITION_MAP[key]
            print(f"✓ [{r.method:6}] {r.path:<48} | {mod:<12} | {cat}")
        else:
            missing_disposition.append(r)
            print(f"✗ [{r.method:6}] {r.path:<48} | UNKNOWN DISPOSITION")

    print("-" * 75)
    if missing_disposition:
        print(f"FAILED: {len(missing_disposition)} routes are missing a documented disposition!")
        return 1

    print("SUCCESS: All registered routes have documented dispositions.")
    return 0


if __name__ == "__main__":
    sys.exit(verify_route_inventory())
