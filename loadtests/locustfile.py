"""TaskFlow Locust Load Testing Suite.

Implements realistic user journeys, Kanban workflows, tenant isolation checks,
administrative governance, and specialized security scenarios.
"""

from datetime import datetime, timezone
import json
import os
import random
import time
import uuid

from locust import HttpUser, between, events, tag, task

# Configurable environment settings
API_PREFIX = "/api/v1"
TEST_PASSWORD = os.getenv("LOADTEST_PASSWORD", "LoadTestPass123!Secure")
USER_PREFIX = os.getenv("LOADTEST_USER_PREFIX", "lt_user")


def random_slug(prefix: str = "org") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def random_key(prefix: str = "PRJ") -> str:
    return f"{prefix}{uuid.uuid4().hex[:4].upper()}"


class AnonymousUser(HttpUser):
    """Anonymous user checking health and public endpoints."""

    wait_time = between(1.0, 3.0)

    @tag("health", "smoke")
    @task(5)
    def check_health(self) -> None:
        with self.client.get("/health", catch_response=True) as response:
            if response.status_code == 200 and response.json().get("status") == "ok":
                response.success()
            else:
                response.failure(f"Health check failed: {response.status_code} - {response.text}")


class AuthenticatedBaseUser(HttpUser):
    """Base class providing authentication, token lifecycle, and session management."""

    abstract = True
    wait_time = between(0.5, 2.0)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.user_id: str | None = None
        self.email: str | None = None
        self.access_token: str | None = None
        self.refresh_token: str | None = None
        self.auth_headers: dict[str, str] = {}
        self.org_id: str | None = None
        self.project_id: str | None = None
        self.board_id: str | None = None
        self.list_ids: list[str] = []
        self.task_ids: list[dict[str, any]] = []  # dict with id, version, list_id

    def on_start(self) -> None:
        """Register and authenticate a unique test user."""
        unique_id = uuid.uuid4().hex[:10]
        self.email = f"{USER_PREFIX}_{unique_id}@example.com"
        full_name = f"LoadTester {unique_id}"

        # 1. Register User
        reg_payload = {
            "email": self.email,
            "password": TEST_PASSWORD,
            "full_name": full_name,
        }
        with self.client.post(
            f"{API_PREFIX}/auth/register",
            json=reg_payload,
            name="POST /api/v1/auth/register",
            catch_response=True,
        ) as resp:
            if resp.status_code not in (201, 409):
                resp.failure(f"Registration failed: {resp.status_code} {resp.text}")
                return
            resp.success()

        # 2. Login via OAuth2 Password Flow
        login_data = {
            "username": self.email,
            "password": TEST_PASSWORD,
        }
        with self.client.post(
            f"{API_PREFIX}/auth/token",
            data=login_data,
            name="POST /api/v1/auth/token",
            catch_response=True,
        ) as resp:
            if resp.status_code == 200:
                data = resp.json()
                self.access_token = data["access_token"]
                self.user_id = data["user"]["id"]
                self.auth_headers = {"Authorization": f"Bearer {self.access_token}"}

                # Extract refresh token cookie
                self.refresh_token = resp.cookies.get("refresh_token")
                resp.success()
            else:
                resp.failure(f"Login failed: {resp.status_code} {resp.text}")
                return

        # 3. Initialize workspace if needed
        self.setup_test_workspace()

    def setup_test_workspace(self) -> None:
        """Ensure the user has an organization, project, board, and list for testing."""
        if not self.access_token:
            return

        # List organizations
        resp = self.client.get(
            f"{API_PREFIX}/organizations",
            headers=self.auth_headers,
            name="SETUP GET /api/v1/organizations",
        )
        if resp.status_code == 200 and resp.json():
            self.org_id = resp.json()[0]["id"]
        else:
            # Create organization
            org_payload = {
                "name": f"Workspace {uuid.uuid4().hex[:6]}",
                "slug": random_slug(),
            }
            create_resp = self.client.post(
                f"{API_PREFIX}/organizations",
                json=org_payload,
                headers=self.auth_headers,
                name="SETUP POST /api/v1/organizations",
            )
            if create_resp.status_code == 201:
                self.org_id = create_resp.json()["id"]

        if not self.org_id:
            return

        # Check / create project
        p_resp = self.client.get(
            f"{API_PREFIX}/organizations/{self.org_id}/projects",
            headers=self.auth_headers,
            name="SETUP GET /api/v1/organizations/{id}/projects",
        )
        if p_resp.status_code == 200 and p_resp.json():
            self.project_id = p_resp.json()[0]["id"]
        else:
            p_payload = {
                "name": f"Project {uuid.uuid4().hex[:4]}",
                "key": random_key(),
                "description": "Load testing project",
                "visibility": "ORG_PUBLIC",
            }
            create_p = self.client.post(
                f"{API_PREFIX}/organizations/{self.org_id}/projects",
                json=p_payload,
                headers=self.auth_headers,
                name="SETUP POST /api/v1/organizations/{id}/projects",
            )
            if create_p.status_code == 201:
                self.project_id = create_p.json()["id"]

        if not self.project_id:
            return

        # Check / create board
        b_payload = {
            "name": f"Board {uuid.uuid4().hex[:4]}",
            "description": "Load testing board",
        }
        b_resp = self.client.post(
            f"{API_PREFIX}/projects/{self.project_id}/boards",
            json=b_payload,
            headers=self.auth_headers,
            name="SETUP POST /api/v1/projects/{id}/boards",
        )
        if b_resp.status_code == 201:
            self.board_id = b_resp.json()["id"]

        if not self.board_id:
            return

        # Create two lists
        for title in ["To Do", "Done"]:
            l_payload = {"name": title}
            l_resp = self.client.post(
                f"{API_PREFIX}/boards/{self.board_id}/lists",
                json=l_payload,
                headers=self.auth_headers,
                name="SETUP POST /api/v1/boards/{id}/lists",
            )
            if l_resp.status_code == 201:
                self.list_ids.append(l_resp.json()["id"])

        # Create one initial task
        if self.list_ids:
            t_payload = {
                "title": "Initial Load Test Task",
                "priority": "MEDIUM",
            }
            t_resp = self.client.post(
                f"{API_PREFIX}/lists/{self.list_ids[0]}/tasks",
                json=t_payload,
                headers=self.auth_headers,
                name="SETUP POST /api/v1/lists/{id}/tasks",
            )
            if t_resp.status_code == 201:
                t_data = t_resp.json()
                self.task_ids.append({
                    "id": t_data["id"],
                    "version": t_data["version"],
                    "list_id": self.list_ids[0],
                })

    def on_stop(self) -> None:
        """Gracefully logout session on worker stop."""
        if self.refresh_token:
            self.client.post(
                f"{API_PREFIX}/auth/logout",
                headers=self.auth_headers,
                cookies={"refresh_token": self.refresh_token},
                name="POST /api/v1/auth/logout",
            )


class KanbanStandardUser(AuthenticatedBaseUser):
    """Simulates active team members interacting with Kanban boards, tasks, comments, and notifications."""

    @tag("kanban", "smoke")
    @task(10)
    def view_board_tree(self) -> None:
        """Fetch eager Kanban board tree (Board -> Lists -> Tasks)."""
        if not self.board_id:
            return

        with self.client.get(
            f"{API_PREFIX}/boards/{self.board_id}",
            headers=self.auth_headers,
            name="GET /api/v1/boards/{board_id}",
            catch_response=True,
        ) as resp:
            if resp.status_code == 200:
                data = resp.json()
                # Update cached task versions
                for lst in data.get("lists", []):
                    for t in lst.get("tasks", []):
                        for cached in self.task_ids:
                            if cached["id"] == t["id"]:
                                cached["version"] = t["version"]
                                cached["list_id"] = lst["id"]
                resp.success()
            else:
                resp.failure(f"Board fetch failed: {resp.status_code}")

    @tag("kanban", "tasks")
    @task(5)
    def task_lifecycle_and_mutation(self) -> None:
        """Create a task, update its content, and delete it to prevent unbounded growth."""
        if not self.list_ids:
            return

        target_list = random.choice(self.list_ids)
        t_payload = {
            "title": f"Task {uuid.uuid4().hex[:6]}",
            "description": "Created during load test",
            "priority": "HIGH",
        }

        # 1. Create Task
        with self.client.post(
            f"{API_PREFIX}/lists/{target_list}/tasks",
            json=t_payload,
            headers=self.auth_headers,
            name="POST /api/v1/lists/{list_id}/tasks",
            catch_response=True,
        ) as create_resp:
            if create_resp.status_code != 201:
                create_resp.failure(f"Task creation failed: {create_resp.status_code}")
                return
            create_resp.success()
            created = create_resp.json()
            task_id = created["id"]
            version = created["version"]

        # 2. Update Task
        update_payload = {
            "expected_version": version,
            "title": f"Updated Task {uuid.uuid4().hex[:6]}",
            "priority": "URGENT",
        }
        with self.client.patch(
            f"{API_PREFIX}/tasks/{task_id}",
            json=update_payload,
            headers=self.auth_headers,
            name="PATCH /api/v1/tasks/{task_id}",
            catch_response=True,
        ) as update_resp:
            if update_resp.status_code in (200, 409):
                update_resp.success()
            else:
                update_resp.failure(f"Task update failed: {update_resp.status_code}")

        # 3. Soft-delete Task to bound DB size
        with self.client.delete(
            f"{API_PREFIX}/tasks/{task_id}",
            headers=self.auth_headers,
            name="DELETE /api/v1/tasks/{task_id}",
            catch_response=True,
        ) as del_resp:
            if del_resp.status_code == 204:
                del_resp.success()
            else:
                del_resp.failure(f"Task deletion failed: {del_resp.status_code}")

    @tag("kanban", "occ")
    @task(6)
    def move_task_occ(self) -> None:
        """Execute O(1) single-row task move with OCC version verification."""
        if not self.task_ids or len(self.list_ids) < 2:
            return

        target_task = random.choice(self.task_ids)
        current_list = target_task["list_id"]
        # Alternate target list
        next_list = self.list_ids[1] if current_list == self.list_ids[0] else self.list_ids[0]

        move_payload = {
            "target_list_id": next_list,
            "expected_version": target_task["version"],
        }

        with self.client.post(
            f"{API_PREFIX}/tasks/{target_task['id']}/move",
            json=move_payload,
            headers=self.auth_headers,
            name="POST /api/v1/tasks/{task_id}/move",
            catch_response=True,
        ) as resp:
            if resp.status_code == 200:
                data = resp.json()
                target_task["version"] = data["version"]
                target_task["list_id"] = next_list
                resp.success()
            elif resp.status_code == 409:
                # 409 Conflict is expected OCC behavior under concurrent modification
                err = resp.json().get("error", {})
                if err.get("code") == "TASK_VERSION_CONFLICT":
                    curr_ver = err.get("details", {}).get("current_version")
                    if curr_ver:
                        target_task["version"] = curr_ver
                    resp.success()
                else:
                    resp.failure(f"Unexpected 409 error structure: {resp.text}")
            else:
                resp.failure(f"Task move failed: {resp.status_code} {resp.text}")

    @tag("comments")
    @task(4)
    def comment_lifecycle(self) -> None:
        """Create, read, update, and delete comments on tasks."""
        if not self.task_ids:
            return

        task_id = self.task_ids[0]["id"]

        # 1. Create Comment
        c_payload = {"content": f"Load test note at {time.time()}"}
        with self.client.post(
            f"{API_PREFIX}/tasks/{task_id}/comments",
            json=c_payload,
            headers=self.auth_headers,
            name="POST /api/v1/tasks/{task_id}/comments",
            catch_response=True,
        ) as resp:
            if resp.status_code != 201:
                resp.failure(f"Comment creation failed: {resp.status_code}")
                return
            resp.success()
            comment_id = resp.json()["id"]

        # 2. List Comments
        with self.client.get(
            f"{API_PREFIX}/tasks/{task_id}/comments",
            headers=self.auth_headers,
            name="GET /api/v1/tasks/{task_id}/comments",
            catch_response=True,
        ) as list_resp:
            if list_resp.status_code == 200:
                list_resp.success()
            else:
                list_resp.failure(f"Comment list failed: {list_resp.status_code}")

        # 3. Update Comment (Author-only edit)
        patch_payload = {"content": "Updated comment content by author"}
        with self.client.patch(
            f"{API_PREFIX}/comments/{comment_id}",
            json=patch_payload,
            headers=self.auth_headers,
            name="PATCH /api/v1/comments/{comment_id}",
            catch_response=True,
        ) as patch_resp:
            if patch_resp.status_code == 200:
                patch_resp.success()
            else:
                patch_resp.failure(f"Comment update failed: {patch_resp.status_code}")

        # 4. Delete Comment
        with self.client.delete(
            f"{API_PREFIX}/comments/{comment_id}",
            headers=self.auth_headers,
            name="DELETE /api/v1/comments/{comment_id}",
            catch_response=True,
        ) as del_resp:
            if del_resp.status_code == 204:
                del_resp.success()
            else:
                del_resp.failure(f"Comment deletion failed: {del_resp.status_code}")

    @tag("notifications")
    @task(3)
    def notifications_inbox(self) -> None:
        """Inspect notifications inbox, mark individual notification as read, and batch mark read."""
        # 1. List notifications
        with self.client.get(
            f"{API_PREFIX}/notifications",
            headers=self.auth_headers,
            name="GET /api/v1/notifications",
            catch_response=True,
        ) as resp:
            if resp.status_code != 200:
                resp.failure(f"Notifications fetch failed: {resp.status_code}")
                return
            resp.success()
            items = resp.json().get("items", [])

        # 2. If an unread notification exists, mark it as read
        unread = [n for n in items if not n.get("is_read")]
        if unread:
            target_id = unread[0]["id"]
            with self.client.patch(
                f"{API_PREFIX}/notifications/{target_id}/read",
                headers=self.auth_headers,
                name="PATCH /api/v1/notifications/{id}/read",
                catch_response=True,
            ) as read_resp:
                if read_resp.status_code == 200:
                    read_resp.success()
                else:
                    read_resp.failure(f"Mark read failed: {read_resp.status_code}")

        # 3. Batch mark all as read
        with self.client.post(
            f"{API_PREFIX}/notifications/mark-all-read",
            headers=self.auth_headers,
            name="POST /api/v1/notifications/mark-all-read",
            catch_response=True,
        ) as batch_resp:
            if batch_resp.status_code == 204:
                batch_resp.success()
            else:
                batch_resp.failure(f"Mark all read failed: {batch_resp.status_code}")

    @tag("users")
    @task(2)
    def user_profile_workflow(self) -> None:
        """Get and update caller user profile."""
        with self.client.get(
            f"{API_PREFIX}/users/me",
            headers=self.auth_headers,
            name="GET /api/v1/users/me",
            catch_response=True,
        ) as resp:
            if resp.status_code == 200:
                resp.success()
            else:
                resp.failure(f"User profile fetch failed: {resp.status_code}")

        update_payload = {"full_name": f"Tester {uuid.uuid4().hex[:6]}"}
        with self.client.patch(
            f"{API_PREFIX}/users/me",
            json=update_payload,
            headers=self.auth_headers,
            name="PATCH /api/v1/users/me",
            catch_response=True,
        ) as patch_resp:
            if patch_resp.status_code == 200:
                patch_resp.success()
            else:
                patch_resp.failure(f"User profile update failed: {patch_resp.status_code}")

    @tag("auth")
    @task(1)
    def token_refresh_flow(self) -> None:
        """Test token rotation with X-Refresh-Operation-Id and HttpOnly cookie."""
        if not self.refresh_token:
            return

        op_id = str(uuid.uuid4())
        refresh_headers = {
            "X-Refresh-Operation-Id": op_id,
        }
        with self.client.post(
            f"{API_PREFIX}/auth/refresh",
            headers=refresh_headers,
            cookies={"refresh_token": self.refresh_token},
            name="POST /api/v1/auth/refresh",
            catch_response=True,
        ) as resp:
            if resp.status_code == 200:
                data = resp.json()
                self.access_token = data["access_token"]
                self.auth_headers = {"Authorization": f"Bearer {self.access_token}"}
                new_cookie = resp.cookies.get("refresh_token")
                if new_cookie:
                    self.refresh_token = new_cookie
                resp.success()
            else:
                resp.failure(f"Token refresh failed: {resp.status_code} {resp.text}")


class OrgAdminUser(AuthenticatedBaseUser):
    """Simulates workspace administrators managing members, invitations, projects, and audit logs."""

    @tag("admin", "members")
    @task(4)
    def manage_organization_members(self) -> None:
        """List organization members and audit logs."""
        if not self.org_id:
            return

        with self.client.get(
            f"{API_PREFIX}/organizations/{self.org_id}/members",
            headers=self.auth_headers,
            name="GET /api/v1/organizations/{id}/members",
            catch_response=True,
        ) as resp:
            if resp.status_code == 200:
                resp.success()
            else:
                resp.failure(f"List members failed: {resp.status_code}")

        with self.client.get(
            f"{API_PREFIX}/organizations/{self.org_id}/audit-logs",
            headers=self.auth_headers,
            name="GET /api/v1/organizations/{id}/audit-logs",
            catch_response=True,
        ) as audit_resp:
            if audit_resp.status_code == 200:
                audit_resp.success()
            else:
                audit_resp.failure(f"Audit logs fetch failed: {audit_resp.status_code}")

    @tag("admin", "invitations")
    @task(3)
    def invitations_lifecycle(self) -> None:
        """Create, list, and revoke pending member invitations."""
        if not self.org_id:
            return

        target_email = f"invitee_{uuid.uuid4().hex[:8]}@example.com"
        inv_payload = {
            "email": target_email,
            "role": "MEMBER",
        }

        # 1. Create invitation
        with self.client.post(
            f"{API_PREFIX}/organizations/{self.org_id}/invitations",
            json=inv_payload,
            headers=self.auth_headers,
            name="POST /api/v1/organizations/{id}/invitations",
            catch_response=True,
        ) as create_resp:
            if create_resp.status_code != 201:
                create_resp.failure(f"Invitation create failed: {create_resp.status_code}")
                return
            create_resp.success()
            invitation_id = create_resp.json()["id"]

        # 2. List invitations
        with self.client.get(
            f"{API_PREFIX}/organizations/{self.org_id}/invitations",
            headers=self.auth_headers,
            name="GET /api/v1/organizations/{id}/invitations",
            catch_response=True,
        ) as list_resp:
            if list_resp.status_code == 200:
                list_resp.success()
            else:
                list_resp.failure(f"List invitations failed: {list_resp.status_code}")

        # 3. Revoke invitation
        with self.client.delete(
            f"{API_PREFIX}/organizations/{self.org_id}/invitations/{invitation_id}",
            headers=self.auth_headers,
            name="DELETE /api/v1/organizations/{id}/invitations/{id}",
            catch_response=True,
        ) as del_resp:
            if del_resp.status_code == 204:
                del_resp.success()
            else:
                del_resp.failure(f"Revoke invitation failed: {del_resp.status_code}")

    @tag("admin", "projects")
    @task(3)
    def project_and_members_management(self) -> None:
        """Inspect project details, list members, update details."""
        if not self.project_id:
            return

        # 1. Get project details
        with self.client.get(
            f"{API_PREFIX}/projects/{self.project_id}",
            headers=self.auth_headers,
            name="GET /api/v1/projects/{project_id}",
            catch_response=True,
        ) as get_resp:
            if get_resp.status_code == 200:
                get_resp.success()
            else:
                get_resp.failure(f"Get project failed: {get_resp.status_code}")

        # 2. Update project
        patch_payload = {
            "name": f"Renamed Project {uuid.uuid4().hex[:4]}",
            "description": "Updated under administrative load test",
        }
        with self.client.patch(
            f"{API_PREFIX}/projects/{self.project_id}",
            json=patch_payload,
            headers=self.auth_headers,
            name="PATCH /api/v1/projects/{project_id}",
            catch_response=True,
        ) as patch_resp:
            if patch_resp.status_code == 200:
                patch_resp.success()
            else:
                patch_resp.failure(f"Update project failed: {patch_resp.status_code}")

        # 3. List project members
        with self.client.get(
            f"{API_PREFIX}/projects/{self.project_id}/members",
            headers=self.auth_headers,
            name="GET /api/v1/projects/{project_id}/members",
            catch_response=True,
        ) as members_resp:
            if members_resp.status_code == 200:
                members_resp.success()
            else:
                members_resp.failure(f"List project members failed: {members_resp.status_code}")

    @tag("admin", "lists")
    @task(2)
    def reorder_list_occ(self) -> None:
        """Reorder board lists horizontally with OCC."""
        if len(self.list_ids) < 2:
            return

        list_to_move = self.list_ids[0]
        # Invert order
        move_payload = {
            "prev_list_id": self.list_ids[1],
            "expected_version": 1,
        }
        with self.client.post(
            f"{API_PREFIX}/lists/{list_to_move}/move",
            json=move_payload,
            headers=self.auth_headers,
            name="POST /api/v1/lists/{list_id}/move",
            catch_response=True,
        ) as resp:
            # 200 or 409 are expected OCC outcomes
            if resp.status_code in (200, 409):
                resp.success()
            else:
                resp.failure(f"List move failed: {resp.status_code} {resp.text}")


class SecurityAndIsolationUser(AuthenticatedBaseUser):
    """Executes negative tests and boundary verifications for multi-tenancy and security."""

    @tag("security", "isolation")
    @task(5)
    def test_cross_tenant_isolation(self) -> None:
        """Verify non-existent or foreign tenant resources return 404 NOT_FOUND, concealing existence."""
        fake_uuid = str(uuid.uuid4())

        # 1. Foreign organization members
        with self.client.get(
            f"{API_PREFIX}/organizations/{fake_uuid}/members",
            headers=self.auth_headers,
            name="NEGATIVE GET /api/v1/organizations/{fake_id}/members (Expect 404)",
            catch_response=True,
        ) as resp:
            if resp.status_code == 404:
                resp.success()
            else:
                resp.failure(f"Expected 404 for foreign org, got {resp.status_code}")

        # 2. Foreign project
        with self.client.get(
            f"{API_PREFIX}/projects/{fake_uuid}",
            headers=self.auth_headers,
            name="NEGATIVE GET /api/v1/projects/{fake_id} (Expect 404)",
            catch_response=True,
        ) as resp:
            if resp.status_code == 404:
                resp.success()
            else:
                resp.failure(f"Expected 404 for foreign project, got {resp.status_code}")

        # 3. Foreign board
        with self.client.get(
            f"{API_PREFIX}/boards/{fake_uuid}",
            headers=self.auth_headers,
            name="NEGATIVE GET /api/v1/boards/{fake_id} (Expect 404)",
            catch_response=True,
        ) as resp:
            if resp.status_code == 404:
                resp.success()
            else:
                resp.failure(f"Expected 404 for foreign board, got {resp.status_code}")

    @tag("security", "auth")
    @task(3)
    def test_unauthenticated_rejection(self) -> None:
        """Verify endpoints reject requests with missing or invalid bearer tokens."""
        invalid_headers = {"Authorization": "Bearer invalid.token.value"}

        with self.client.get(
            f"{API_PREFIX}/users/me",
            headers=invalid_headers,
            name="NEGATIVE GET /api/v1/users/me (Invalid Token - Expect 401)",
            catch_response=True,
        ) as resp:
            if resp.status_code == 401:
                resp.success()
            else:
                resp.failure(f"Expected 401 for invalid token, got {resp.status_code}")
