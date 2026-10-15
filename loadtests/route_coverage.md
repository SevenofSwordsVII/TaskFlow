# TaskFlow Route Coverage Inventory & Locust Test Strategy

This document tracks all 43 registered API endpoints in TaskFlow, their authentication/role requirements, expected HTTP responses, and their corresponding load testing or automated verification disposition.

---

## 1. Summary Statistics

- **Total API Routes Discovered**: 43
- **Covered in Realistic Locust Load Profiles**: 37 routes
- **Covered in Specialized Lifecycle / Automated Verifications**: 6 routes
- **Intentionally Excluded from High-Frequency Load**: 0 routes (all covered via appropriate load or lifecycle test)
- **Undocumented / Missing Disposition**: 0 routes

---

## 2. Comprehensive Route Inventory & Coverage Matrix

| # | HTTP Method | Route Path | Module | Auth Requirement | Role / Permissions | Request Payload / Params | Expected Success | Expected Errors | Coverage Category | Execution & Test Strategy |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | `GET` | `/health` | System | None | Public | None | 200 OK | - | Normal Load-Test | `AnonymousUser.check_health` |
| 2 | `POST` | `/api/v1/auth/register` | Auth | None | Public | `RegisterRequest` (email, password, full_name) | 201 Created | 400, 409, 422 | Normal Load-Test | `AuthenticatedBaseUser.on_start` |
| 3 | `POST` | `/api/v1/auth/token` | Auth | None | Public | `OAuth2PasswordRequestForm` (username, password) | 200 OK | 400, 401, 422 | Normal Load-Test | `AuthenticatedBaseUser.on_start` (login & cookie capture) |
| 4 | `POST` | `/api/v1/auth/refresh` | Auth | Cookie | Public (`refresh_token` cookie + `X-Refresh-Operation-Id` header) | UUID header + Cookie | 200 OK | 400, 401, 422 | Normal Load-Test | `KanbanStandardUser.token_refresh_flow` |
| 5 | `POST` | `/api/v1/auth/logout` | Auth | Cookie | Public (`refresh_token` cookie) | Cookie | 204 No Content | 400, 401 | Normal Load-Test | `AuthenticatedBaseUser.on_stop` |
| 6 | `GET` | `/api/v1/auth/me` | Auth | Bearer | Authenticated User | None | 200 OK | 401 | Normal Load-Test | `AuthenticatedBaseUser.setup_test_workspace` |
| 7 | `GET` | `/api/v1/users/me` | Users | Bearer | Authenticated User | None | 200 OK | 401 | Normal Load-Test | `KanbanStandardUser.user_profile_workflow` |
| 8 | `PATCH` | `/api/v1/users/me` | Users | Bearer | Authenticated User | `UserUpdate` (full_name, avatar_url) | 200 OK | 400, 401, 422 | Normal Load-Test | `KanbanStandardUser.user_profile_workflow` |
| 9 | `DELETE` | `/api/v1/users/me` | Users | Bearer | Authenticated User | None | 204 No Content | 401, 409 | Specialized Lifecycle | Dedicated user teardown verifying `ON DELETE RESTRICT` sequence |
| 10 | `POST` | `/api/v1/organizations` | Organizations | Bearer | Authenticated User | `OrganizationCreate` (name, slug) | 201 Created | 400, 401, 409, 422 | Normal Load-Test | `AuthenticatedBaseUser.setup_test_workspace` |
| 11 | `GET` | `/api/v1/organizations` | Organizations | Bearer | Authenticated User | None | 200 OK | 401 | Normal Load-Test | `AuthenticatedBaseUser.setup_test_workspace` |
| 12 | `POST` | `/api/v1/organizations/invitations/accept` | Organizations | Bearer | Authenticated User | `InvitationAcceptRequest` (token) | 200 OK | 400, 401, 403, 404, 409, 422 | Normal Load-Test | Member invitation acceptance flow |
| 13 | `GET` | `/api/v1/organizations/{organization_id}/members` | Organizations | Bearer | Org VIEWER+ | Path `organization_id` | 200 OK | 401, 404 | Normal Load-Test | `OrgAdminUser.manage_organization_members` |
| 14 | `PATCH` | `/api/v1/organizations/{organization_id}/members/{user_id}` | Organizations | Bearer | Org ADMIN+ | `MemberRoleUpdateRequest` (role) | 200 OK | 401, 403, 404, 422 | Normal Load-Test | Org admin member role update workflow |
| 15 | `DELETE` | `/api/v1/organizations/{organization_id}/members/{user_id}` | Organizations | Bearer | Org ADMIN+ | Path `organization_id`, `user_id` | 204 No Content | 401, 403, 404 | Specialized Lifecycle | Member offboarding test (removes test member) |
| 16 | `POST` | `/api/v1/organizations/{organization_id}/transfer-ownership` | Organizations | Bearer | Org OWNER | `TransferOwnershipRequest` (new_owner_user_id) | 204 No Content | 400, 401, 403, 404, 422 | Specialized Lifecycle | Dedicated ownership transfer lifecycle scenario |
| 17 | `POST` | `/api/v1/organizations/{organization_id}/invitations` | Organizations | Bearer | Org ADMIN+ | `InvitationCreate` (email, role) | 201 Created | 400, 401, 403, 404, 409, 422 | Normal Load-Test | `OrgAdminUser.invitations_lifecycle` |
| 18 | `GET` | `/api/v1/organizations/{organization_id}/invitations` | Organizations | Bearer | Org ADMIN+ | Path `organization_id` | 200 OK | 401, 403, 404 | Normal Load-Test | `OrgAdminUser.invitations_lifecycle` |
| 19 | `DELETE` | `/api/v1/organizations/{organization_id}/invitations/{invitation_id}` | Organizations | Bearer | Org ADMIN+ | Path `organization_id`, `invitation_id` | 204 No Content | 401, 403, 404 | Normal Load-Test | `OrgAdminUser.invitations_lifecycle` |
| 20 | `POST` | `/api/v1/organizations/{organization_id}/projects` | Projects | Bearer | Org ADMIN+ | `ProjectCreate` (name, key, description, visibility) | 201 Created | 400, 401, 403, 404, 409, 422 | Normal Load-Test | `AuthenticatedBaseUser.setup_test_workspace` |
| 21 | `GET` | `/api/v1/organizations/{organization_id}/projects` | Projects | Bearer | Org VIEWER+ | Path `organization_id` | 200 OK | 401, 404 | Normal Load-Test | `AuthenticatedBaseUser.setup_test_workspace` |
| 22 | `GET` | `/api/v1/projects/{project_id}` | Projects | Bearer | Project VIEWER+ | Path `project_id` | 200 OK | 401, 404 | Normal Load-Test | `OrgAdminUser.project_and_members_management` |
| 23 | `PATCH` | `/api/v1/projects/{project_id}` | Projects | Bearer | Project ADMIN+ | `ProjectUpdate` (name, description, visibility, is_archived) | 200 OK | 400, 401, 403, 404, 422 | Normal Load-Test | `OrgAdminUser.project_and_members_management` |
| 24 | `DELETE` | `/api/v1/projects/{project_id}` | Projects | Bearer | Project ADMIN+ | Path `project_id` | 204 No Content | 401, 403, 404 | Specialized Lifecycle | Project teardown test |
| 25 | `GET` | `/api/v1/projects/{project_id}/members` | Projects | Bearer | Project VIEWER+ | Path `project_id` | 200 OK | 401, 404 | Normal Load-Test | `OrgAdminUser.project_and_members_management` |
| 26 | `POST` | `/api/v1/projects/{project_id}/members` | Projects | Bearer | Project ADMIN+ | `ProjectMemberCreate` (user_id, project_role) | 201 Created | 400, 401, 403, 404, 409, 422 | Normal Load-Test | Project member assignment workflow |
| 27 | `DELETE` | `/api/v1/projects/{project_id}/members/{user_id}` | Projects | Bearer | Project ADMIN+ | Path `project_id`, `user_id` | 204 No Content | 401, 403, 404 | Specialized Lifecycle | Project member unassignment workflow |
| 28 | `POST` | `/api/v1/projects/{project_id}/boards` | Kanban | Bearer | Authenticated User | `BoardCreate` (name, description) | 201 Created | 400, 401, 404, 422 | Normal Load-Test | `AuthenticatedBaseUser.setup_test_workspace` |
| 29 | `GET` | `/api/v1/boards/{board_id}` | Kanban | Bearer | Authenticated User | Path `board_id` | 200 OK | 401, 404 | Normal Load-Test | `KanbanStandardUser.view_board_tree` |
| 30 | `POST` | `/api/v1/boards/{board_id}/lists` | Kanban | Bearer | Authenticated User | `ListCreate` (name, prev_list_id) | 201 Created | 400, 401, 404, 422 | Normal Load-Test | `AuthenticatedBaseUser.setup_test_workspace` |
| 31 | `POST` | `/api/v1/lists/{list_id}/move` | Kanban | Bearer | Authenticated User | `ListMoveRequest` (prev_list_id, next_list_id, expected_version) | 200 OK | 400, 401, 404, 409, 422 | Normal Load-Test | `OrgAdminUser.reorder_list_occ` |
| 32 | `POST` | `/api/v1/lists/{list_id}/tasks` | Kanban | Bearer | Authenticated User | `TaskCreate` (title, description, priority, prev_task_id) | 201 Created | 400, 401, 404, 422 | Normal Load-Test | `KanbanStandardUser.task_lifecycle_and_mutation` |
| 33 | `PATCH` | `/api/v1/tasks/{task_id}` | Kanban | Bearer | Authenticated User | `TaskUpdate` (expected_version, title, description, priority) | 200 OK | 400, 401, 404, 409, 422 | Normal Load-Test | `KanbanStandardUser.task_lifecycle_and_mutation` |
| 34 | `POST` | `/api/v1/tasks/{task_id}/move` | Kanban | Bearer | Authenticated User | `TaskMoveRequest` (target_list_id, prev_task_id, expected_version) | 200 OK | 400, 401, 404, 409, 422 | Normal Load-Test | `KanbanStandardUser.move_task_occ` |
| 35 | `DELETE` | `/api/v1/tasks/{task_id}` | Kanban | Bearer | Authenticated User | Path `task_id` | 204 No Content | 401, 404 | Normal Load-Test | `KanbanStandardUser.task_lifecycle_and_mutation` |
| 36 | `POST` | `/api/v1/tasks/{task_id}/comments` | Comments | Bearer | Authenticated User | `CommentCreate` (content) | 201 Created | 400, 401, 404, 422 | Normal Load-Test | `KanbanStandardUser.comment_lifecycle` |
| 37 | `GET` | `/api/v1/tasks/{task_id}/comments` | Comments | Bearer | Authenticated User | Path `task_id` | 200 OK | 401, 404 | Normal Load-Test | `KanbanStandardUser.comment_lifecycle` |
| 38 | `PATCH` | `/api/v1/comments/{comment_id}` | Comments | Bearer | Comment Author | `CommentUpdate` (content) | 200 OK | 400, 401, 403, 404, 422 | Normal Load-Test | `KanbanStandardUser.comment_lifecycle` |
| 39 | `DELETE` | `/api/v1/comments/{comment_id}` | Comments | Bearer | Comment Author / Admin | Path `comment_id` | 204 No Content | 401, 403, 404 | Normal Load-Test | `KanbanStandardUser.comment_lifecycle` |
| 40 | `GET` | `/api/v1/notifications` | Notifications | Bearer | Authenticated User | None | 200 OK | 401 | Normal Load-Test | `KanbanStandardUser.notifications_inbox` |
| 41 | `PATCH` | `/api/v1/notifications/{notification_id}/read` | Notifications | Bearer | Notification Owner | Path `notification_id` | 200 OK | 401, 404 | Normal Load-Test | `KanbanStandardUser.notifications_inbox` |
| 42 | `POST` | `/api/v1/notifications/mark-all-read` | Notifications | Bearer | Authenticated User | None | 204 No Content | 401 | Normal Load-Test | `KanbanStandardUser.notifications_inbox` |
| 43 | `GET` | `/api/v1/organizations/{organization_id}/audit-logs` | Audit Logs | Bearer | Org ADMIN+ | Path `organization_id` | 200 OK | 401, 403, 404 | Normal Load-Test | `OrgAdminUser.manage_organization_members` |

---

## 3. Specialized Lifecycle Scenarios

The following 6 operations have irreversible side-effects on accounts or structural memberships:
1. `DELETE /api/v1/users/me`: Deletes account and revokes tokens. Exercised in a controlled teardown suite to verify the PostgreSQL `ON DELETE RESTRICT` transaction ordering (`refresh_operations` -> `refresh_token_sessions` -> `users`).
2. `POST /api/v1/organizations/{organization_id}/transfer-ownership`: Shifts ownership role permanently from current owner to another member. Executed in dedicated isolated test workspaces.
3. `DELETE /api/v1/organizations/{organization_id}/members/{user_id}`: Removes member from workspace and unassigns tasks.
4. `DELETE /api/v1/projects/{project_id}`: Soft-deletes project.
5. `POST /api/v1/projects/{project_id}/members`: Adds user to restricted project.
6. `DELETE /api/v1/projects/{project_id}/members/{user_id}`: Removes user from restricted project.

Each specialized scenario is verified in `backend/tests/integration/` and can be run under Locust using dedicated lifecycle tasks.
