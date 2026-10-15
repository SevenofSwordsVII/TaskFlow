# TaskFlow Administration Capabilities Audit

**Date of Audit**: October 2026  
**Auditor**: Senior Software Architect & Code Auditor  
**Scope**: Entire TaskFlow Codebase (`backend/`, `frontend/`, `specs/`, database schemas, and configuration)

---

## Executive Summary

This audit assesses the administration capabilities in TaskFlow based strictly on verified source code evidence. It answers whether the platform distinguishes organization-level administration from global site administration, whether a superuser exists with administrative privileges, and whether an administration UI (e.g., SQLAdmin) is present.

### Key Findings Matrix

| Capability Category | Status in Code | Evidence / Location |
| :--- | :--- | :--- |
| **A. Regular Authenticated Users** | **Implemented & Verified** | `backend/app/modules/auth/`, `backend/app/modules/users/`, `frontend/src/pages/LoginPage.tsx`, `RegisterPage.tsx` |
| **B. Organization Owners & Admins** | **Implemented & Verified** | `backend/app/modules/organizations/`, `backend/app/core/dependencies.py`, `frontend/src/features/organizations/` |
| **C. Global Site Administrator / Superuser** | **Implemented & Verified** | `User.is_superuser` column active; CLI management commands in `backend/app/cli.py`; strictly enforced by `app/admin/auth.py` |
| **D. Dedicated Admin Interface (SQLAdmin)** | **Implemented & Verified** | `sqladmin>=0.20.0` integrated at `/admin` (`backend/app/admin/`); 13 ModelViews; credential exclusion; immutable audit logs; session security |

---

## 1. Regular Authenticated Users (Implemented & Verified)

### Evidence
- **Registration & Login**:
  - `POST /api/v1/auth/register` (`backend/app/modules/auth/router.py:28`): Allows open public registration with Argon2id password hashing.
  - `POST /api/v1/auth/token` (`backend/app/modules/auth/router.py:43`): OAuth2 Password Request Form endpoint returning short-lived (15-minute) stateless JWT Bearer tokens and setting an `HttpOnly`, `SameSite=Lax` refresh cookie.
- **Session Lifecycle & Token Rotation**:
  - `POST /api/v1/auth/refresh` (`backend/app/modules/auth/router.py:84`): Rotates refresh tokens adhering to an Idempotent Refresh Operation protocol with family-level revocation and AES-256-GCM recovery encryption (`backend/app/modules/auth/service.py:120`).
  - `POST /api/v1/auth/logout` (`backend/app/modules/auth/router.py:145`): Revokes the refresh token family and clears cookies.
- **Profile Management**:
  - `GET /api/v1/auth/me` (`backend/app/modules/auth/router.py:159`): Retrieves the caller's profile and list of organizations.
  - `GET /api/v1/users/me` (`backend/app/modules/users/router.py:15`): Returns personal profile.
  - `PATCH /api/v1/users/me` (`backend/app/modules/users/router.py:27`): Updates profile (full name, avatar URL).
  - `DELETE /api/v1/users/me` (`backend/app/modules/users/router.py:40`): Soft-deletes own user account, respecting foreign key restrictions.
- **User Scope**:
  - Users have no global visibility into other users. There is no `GET /api/v1/users` endpoint to list users across the platform.

---

## 2. Organization-Level Administration (Implemented & Verified)

TaskFlow implements multi-tenant Role-Based Access Control (RBAC) scoped strictly to organizations and projects.

### Hierarchy & Model
In `backend/app/modules/organizations/models.py:15`:
```python
class OrganizationRole(str, enum.Enum):
    OWNER = "OWNER"      # Level 4
    ADMIN = "ADMIN"      # Level 3
    MEMBER = "MEMBER"    # Level 2
    VIEWER = "VIEWER"    # Level 1
```

In `backend/app/core/dependencies.py:25`:
```python
ROLE_HIERARCHY: dict[str, int] = {
    "OWNER": 4,
    "ADMIN": 3,
    "MEMBER": 2,
    "VIEWER": 1,
}
```

### Enforced Capabilities by Organization Role

1. **Organization Creation**:
   - `POST /api/v1/organizations` (`backend/app/modules/organizations/router.py:33`): Any active authenticated user can create an organization. The creator is automatically assigned the `OWNER` role (`backend/app/modules/organizations/service.py:75`).
2. **Member Invitation & Management (`OWNER` or `ADMIN`)**:
   - `POST /api/v1/organizations/{organization_id}/invitations`: Create member invitations with a specific role (`ADMIN`, `MEMBER`, or `VIEWER`). Tokens are stored as SHA-256 hashes (`backend/app/modules/organizations/service.py:340`).
   - `GET /api/v1/organizations/{organization_id}/invitations`: List pending invitations.
   - `DELETE /api/v1/organizations/{organization_id}/invitations/{invitation_id}`: Revoke pending invitation.
   - `PATCH /api/v1/organizations/{organization_id}/members/{user_id}`: Change a member's role. An `ADMIN` cannot promote anyone to `OWNER`.
   - `DELETE /api/v1/organizations/{organization_id}/members/{user_id}`: Remove a member. Tasks assigned to the removed member within the organization are atomically unassigned (`service.py:230`). An `ADMIN` cannot remove another `ADMIN` or the `OWNER`; only an `OWNER` can remove an `ADMIN`.
3. **Ownership Transfer (`OWNER` Only)**:
   - `POST /api/v1/organizations/{organization_id}/transfer-ownership` (`backend/app/modules/organizations/router.py:141`): Atomically transfers `OWNER` role to another active member and demotes the current caller to `ADMIN`.
4. **Governance & Audit Trail (`OWNER` or `ADMIN`)**:
   - `GET /api/v1/organizations/{organization_id}/audit-logs` (`backend/app/modules/audit_logs/router.py:20`): Lists immutable audit log events (membership changes, role mutations, ownership transfers, project lifecycles) for that organization only.
5. **Project Management (`OWNER` or `ADMIN`)**:
   - `POST /api/v1/organizations/{organization_id}/projects` (`backend/app/modules/projects/router.py:37`): Creating projects requires at least `ADMIN` in the organization.
   - `PATCH /api/v1/projects/{project_id}` and `DELETE /api/v1/projects/{project_id}`: Project updates and soft-deletion require project or organization `ADMIN`.

### Tenant Concealment Guarantee
In `backend/app/core/dependencies.py:126` (`require_org_role`):
- If a user attempts to access an organization where they are not an active member, the system raises `NotFoundException(code="ORGANIZATION_NOT_FOUND", status_code=404)`.
- **Tenant Concealment Invariant**: An attacker or unauthorized user receives HTTP 404 rather than HTTP 403, preventing organization ID enumeration and tenant boundary discovery across workspaces.

---

## 3. Global Site Administration (Missing / Inert Schema Only)

### Status: MISSING / DORMANT

#### Database Schema Reality
- The `users` table has an `is_superuser` boolean column:
  - Definition: `backend/app/modules/users/models.py:36` (`is_superuser: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)`).
  - Migration: `backend/alembic/versions/001_initial_auth_and_orgs.py:31` (`sa.Column("is_superuser", sa.Boolean(), server_default=sa.text("false"), nullable=False)`).
  - User registration: `backend/app/modules/auth/service.py:58` always sets `is_superuser=False`.
  - Schema: `backend/app/modules/users/schemas.py:40` exposes `is_superuser: bool` in `UserRead`.

#### Verification of Enforcement & Routes
An exhaustive search across `backend/app/` reveals:
1. **Zero Route Protection**: There is no `require_superuser` or `require_global_admin` dependency in `backend/app/core/dependencies.py` or anywhere else.
2. **Zero Global Endpoints**:
   - No `GET /api/v1/admin/users` to view or search platform users.
   - No `PATCH /api/v1/admin/users/{user_id}/status` to disable, suspend, or ban abusive users.
   - No `GET /api/v1/admin/organizations` to list or monitor all organizations across the database.
   - No `GET /api/v1/admin/audit-logs` for system-wide audit monitoring.
3. **No Superuser Bypass**: Even if a user record in PostgreSQL has `is_superuser = true`, `require_org_role` in `backend/app/core/dependencies.py` will still raise HTTP 404 if the user is not explicitly registered in `organization_members` for the target organization. The system does not recognize global administrative overrides.
4. **Frontend Interface**: The frontend application (`frontend/src/`) contains zero global administration pages, routes, or superuser UI components.

---

## 4. Dedicated Administrative Interface (Missing)

### Status: NOT IMPLEMENTED

#### Verification
- **Package Dependencies (`backend/pyproject.toml`)**:
  - `sqladmin`, `fastapi-admin`, `starlette-admin`, `flask-admin`, and `django` are **not installed** or listed as dependencies.
  - The only installed web and database packages are `fastapi>=0.115.0`, `uvicorn[standard]>=0.30.0`, `sqlalchemy[asyncio]>=2.0.35`, `asyncpg>=0.29.0`, and `alembic>=1.13.0`.
- **Application Mounting (`backend/app/main.py`)**:
  - No admin engine or ASGI mount (such as `Admin(app, engine)`) is initialized or attached.
- **Frontend Pages**:
  - The UI provides organization-level settings (`/settings/members`, `/settings/audit-logs`, `/projects/:projectId/settings`), but no global dashboard exists.

---

## 5. Security Implications & Operational Gaps

1. **Multi-Tenancy Strength**:
   - Tenant isolation is strictly enforced at the database query level and dependency layer. An organization owner or administrator cannot view or modify data outside their own workspace.
2. **Platform Management Limitation**:
   - SaaS operators currently have no administrative control plane.
   - Banning a malicious user, inspecting orphaned organizations, or managing database records requires direct SQL access to the PostgreSQL instance (`docker compose exec db psql -U taskflow -d taskflow`).
3. **Account Deletion / Inactivity Handling**:
   - While users can self-delete via `DELETE /api/v1/users/me`, platform administrators cannot deactivate an account or reassign abandoned workspaces via an API.

---

## 6. Architectural Recommendations

---

## 5. Global Administration & SQLAdmin Implementation (Implemented & Verified)

Following the initial audit, full-featured global platform administration was designed and implemented using **SQLAdmin 0.32.0** and async SQLAlchemy 2.x without compromising multi-tenant security or creating synchronous engine bottlenecks.

### Verified Architecture & Components

1. **Async-Native Engine Integration (`backend/app/admin/setup.py`)**:
   - Reuses `app.core.database.engine` (`AsyncEngine`) and `AsyncSessionLocal` (`async_sessionmaker[AsyncSession]`) directly.
   - Mounts at `/admin` on the FastAPI application instance.

2. **Server-Side Authentication & Session Security (`backend/app/admin/auth.py`)**:
   - Subclasses `sqladmin.authentication.AuthenticationBackend` with Starlette session cookie `taskflow_admin_session`.
   - Signed with `ADMIN_SECRET_KEY` (4-hour expiration, `SameSite=Lax`, `HttpOnly`, `Secure` in production).
   - Verifies Argon2id password hashing against `users.hashed_password`.
   - **Strict Access Enforcement**: Re-queries PostgreSQL on every administrative request to guarantee that `is_superuser == True` and `is_active == True`. Sessions belonging to demoted or deactivated accounts are immediately destroyed.
   - Sliding-window IP rate limiting prevents brute-force attempts on `/admin/login`.

3. **Domain Entity ModelViews (`backend/app/admin/views.py`)**:
   - 13 registered ModelViews covering all core domain models (`User`, `Organization`, `OrganizationMember`, `OrganizationInvitation`, `Project`, `ProjectMember`, `Board`, `List`, `Task`, `Comment`, `Notification`, `AuditLog`, `RefreshTokenSession`).
   - **Credential Protection**: Sensitive fields (`hashed_password`, `token_hash`) are strictly excluded from lists, detail views, and edit forms.
   - **Integrity Safeguards**: `AuditLogAdmin` is strictly immutable (`can_create = False`, `can_edit = False`, `can_delete = False`). Direct editing on Kanban `List` columns is disabled to prevent corruption of LexoRank fractional ordering keys and OCC versioning.

4. **Idempotent Administrative CLI (`backend/app/cli.py`)**:
   - `python -m app.cli create-superuser --email ... --password ...`: Provisions or idempotently updates superusers.
   - `python -m app.cli promote-user --email ...`: Promotes existing users to superuser.
   - `python -m app.cli demote-user --email ...`: Revokes superuser privileges.

5. **Security Test Verification (`backend/tests/integration/test_sqladmin_security.py`)**:
   - 14 automated unit and integration tests covering anonymous redirects, ordinary user denial, workspace owner/admin denial, superuser login, logout session clearing, demoted user session revocation, ModelView count and registration, credential exclusion, audit log immutability, and CLI idempotency.
