# TaskFlow

> Production-grade, multi-tenant SaaS project management and Kanban platform built with **FastAPI**, **PostgreSQL 18**, **SQLAlchemy 2.x Async**, **React**, and **TypeScript**.

[![Python](https://img.shields.io/badge/Python-3.12+-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-009688.svg)](https://fastapi.tiangolo.com/)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-18-336791.svg)](https://www.postgresql.org/)
[![React](https://img.shields.io/badge/React-18.3-61DAFB.svg)](https://react.dev/)
[![TypeScript](https://img.shields.io/badge/TypeScript-5.6-3178C6.svg)](https://www.typescriptlang.org/)
[![Docker](https://img.shields.io/badge/Docker-Compose-2496ED.svg)](https://www.docker.com/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](./LICENSE)

---

## Overview

**TaskFlow** is a commercial-quality, multi-tenant SaaS project management solution inspired by Linear and Trello. It provides organizations with strict tenant isolation, role-based governance, and real-time interactive Kanban boards powered by deterministic fractional string ordering (**LexoRank**) and Optimistic Concurrency Control (**OCC**).

### Technical Highlights

- **Modular Monolith & Vertical Slices**: High domain cohesion keeping Boards, Lists, and Tasks encapsulated in a single domain module rather than artificial cross-service fragmentation.
- **Strict Multi-Tenancy & Tenant Concealment**: Organization-scoped RBAC where unauthorized access attempts to foreign workspaces return `HTTP 404 Not Found` rather than `403 Forbidden` to prevent workspace enumeration.
- **Idempotent Token Rotation & Zero-Storage Access Tokens**: Access tokens are kept exclusively in client runtime memory (never `localStorage` or `sessionStorage`). Refresh tokens are persisted in `HttpOnly`, `SameSite=Lax` cookies, protected by family-level revocation, cross-tab Web Locks, and AES-256-GCM recovery encryption.
- **Conflict-Resilient Kanban Engine**: O(1) single-row task moves using PostgreSQL row-level locks (`SELECT ... FOR UPDATE`), Optimistic Concurrency Control (version increments), and client-side optimistic UI with rollback on 409 conflicts.
- **Immutable Governance Audit Logs**: Append-only audit trail capturing security-sensitive events (ownership transfers, membership mutations, role updates, project lifecycles).
- **Global Platform Administration (SQLAdmin)**: High-security administrative interface mounted at `/admin`, powered by async-native Starlette/SQLAdmin, session-based authentication, active database re-validation, and superuser RBAC isolation.

> 📖 **راهنمای جامع فارسی**: مستندات فنی و معماری کامل پروژه به زبان فارسی در فایل [`docs/PROJECT_GUIDE_FA.html`](./docs/PROJECT_GUIDE_FA.html) در دسترس است.  
> 🛡️ **راهنمای جامع پنل مدیریت (SQLAdmin)**: راهنمای فنی و امنیتی پنل مدیریت کلان در فایل [`docs/SQLADMIN_GUIDE_FA.html`](./docs/SQLADMIN_GUIDE_FA.html) در دسترس است.  
> 🔍 **Administration Audit**: An evidence-based analysis distinguishing organization-level administration from platform administration is available in [`docs/ADMIN_AUDIT.md`](./docs/ADMIN_AUDIT.md).

---

## Architecture Overview

```mermaid
graph TD
    subgraph Client ["Client Layer (Browser)"]
        UI["React 18 + TypeScript + Vite"]
        TQ["TanStack Query (Server State Cache)"]
        ZS["Zustand (In-Memory Auth & Transient State)"]
        WL["Web Locks API (Cross-Tab Refresh Coordination)"]
    end

    subgraph Gateway ["Reverse Proxy & Ingress"]
        Nginx["Nginx (Port 5173 / Container Port 80)<br/>• SPA Static Hosting (`try_files`)<br/>• Reverse Proxy `/api/` -> `backend:8000`"]
    end

    subgraph Backend ["Backend API (Modular Monolith)"]
        FastAPI["FastAPI 0.115 (Port 8000)<br/>Python 3.12+ / Uvicorn"]
        Middlewares["Middlewares:<br/>• CorrelationIdMiddleware<br/>• TrustedOriginMiddleware (CSRF)<br/>• CORSMiddleware"]
        AuthModule["auth: Argon2id, JWT, Token Family, AES-GCM Recovery"]
        OrgModule["organizations: Multi-Tenant RBAC, Invitations, Concealment"]
        KanbanModule["kanban: Boards, Lists, Tasks, LexoRank, OCC Moves"]
        CollabModule["collaboration: Comments, Notifications, Audit Logs"]
    end

    subgraph Storage ["Persistence Layer"]
        PG["PostgreSQL 18<br/>SQLAlchemy 2.x Async + asyncpg<br/>Alembic Migrations"]
    end

    UI --> TQ
    UI --> ZS
    TQ --> Nginx
    WL --> Nginx
    Nginx --> FastAPI
    FastAPI --> Middlewares
    Middlewares --> AuthModule
    Middlewares --> OrgModule
    Middlewares --> KanbanModule
    Middlewares --> CollabModule
    AuthModule --> PG
    OrgModule --> PG
    KanbanModule --> PG
    CollabModule --> PG
```

---

## Implemented Features

### 1. Identity & Session Management
- **Registration & Argon2id Hashing**: High-entropy password hashing using Argon2id (`time_cost=3, memory_cost=64MB, parallelism=4`).
- **OAuth2 Password Flow**: Issues short-lived (15 min) JWT access tokens in response bodies.
- **Secure Refresh Protocol**: Issues long-lived (30 days) refresh tokens stored strictly in `HttpOnly` cookies.
- **Token Family Revocation**: Detects token reuse (lineage branching) and immediately revokes all tokens within the compromised session family.
- **Idempotent Refresh Recovery**: Tolerates client connection drops during refresh token rotation via `X-Refresh-Operation-Id` and server-side AES-256-GCM encrypted recovery tokens.
- **Cross-Tab Synchronization**: Uses the browser's `navigator.locks` API to guarantee that concurrent tabs never perform simultaneous refresh operations.

### 2. Multi-Tenancy & RBAC
- **Workspace Isolation**: Workspaces (`organizations`) act as strict boundary containers.
- **Role Hierarchy**: `OWNER` (4) > `ADMIN` (3) > `MEMBER` (2) > `VIEWER` (1).
- **Tenant Concealment**: Unauthorized requests to foreign workspaces return 404 to avoid leaking workspace existence.
- **Invitations Flow**: Cryptographically secure URL-safe tokens hashed via SHA-256 with 7-day expiration.
- **Atomic Member Offboarding**: Removing a member automatically unassigns all of their assigned tasks across the organization in a single transaction.
- **Ownership Transfer**: Dedicated atomic handover protocol from current owner to an active member.

### 3. Projects & Visibility Controls
- **Public vs. Restricted Visibility**:
  - `ORG_PUBLIC`: Accessible to all members of the organization.
  - `RESTRICTED`: Explicit project membership required for `MEMBER` and `VIEWER` roles; organization `OWNER` and `ADMIN` retain supervisory access.
- **Project Scoped Keys**: Short project keys (e.g., `CORE`, `API`) for task identification.

### 4. Kanban Engine & LexoRank
- **Eager Tree Hierarchy**: Single-query retrieval of `Board -> Lists -> Tasks` using SQLAlchemy `selectinload` to prevent N+1 queries.
- **Auto-Initialization**: Opening a project board auto-provisions a default board with `"To Do"`, `"In Progress"`, and `"Done"` columns if none exist.
- **LexoRank String Midpoints**: Deterministic fractional string ordering over base-36 (`0-9a-z`), preserving bucket invariants (`bucket '0'`) without trailing zeros.
- **Optimistic Concurrency Control (OCC)**: Moves increment task `version`. Concurrent moves trigger `HTTP 409 Conflict (TASK_VERSION_CONFLICT)`.
- **Pessimistic Container Locking**: High-concurrency task moves lock parent list containers (`SELECT ... FOR UPDATE`) to prevent race conditions during rank calculations.
- **Optimistic Frontend UI**: Instant client drag-and-drop feedback with automatic state rollback on server error or OCC conflict.

### 5. Collaboration, Notifications & Governance
- **Task Comments**: Threaded discussions with author-only editing and author/admin deletion.
- **Notification Inbox**: Automated event-driven in-app notifications (`TASK_ASSIGNED`, `TASK_COMPLETED`) with unread counters and batch mark-read endpoints.
- **Immutable Audit Trail**: Append-only audit logs capturing actor IDs, target entities, IP addresses, user agents, and JSON payloads.

### 6. Global Platform Administration (SQLAdmin)
- **Async-Native Starlette Architecture**: Integrated directly into FastAPI using `app.core.database.engine` (`AsyncEngine`) and `AsyncSessionLocal` without secondary blocking engines or duplicate ORM models.
- **Strict Superuser Authorization**: Strictly enforces `User.is_superuser == True` and `User.is_active == True`. Workspace roles (`OWNER`, `ADMIN`) are strictly confined to tenant boundaries and cannot access the admin panel.
- **Continuous Session Verification**: The custom `TaskFlowAdminAuth` backend re-validates user existence, active status, and superuser privilege on every request from PostgreSQL, instantly revoking demoted or deactivated sessions.
- **Credential Protection**: Passwords, Argon2id hashes, invitation token hashes, and session hashes are strictly excluded from lists, details, and forms via `form_excluded_columns` and `column_details_exclude_list`.
- **Domain Invariant Safeguards**: `AuditLog` is strictly immutable (`can_create = False`, `can_edit = False`, `can_delete = False`). Kanban `List` direct editing is disabled to preserve LexoRank fractional ordering and OCC versioning.
- **Idempotent Management CLI**: Command-line administrative tooling (`python -m app.cli create-superuser`, `promote-user`, `demote-user`) for secure zero-downtime bootstrap without public privilege escalation endpoints.

---

## Technology Stack

| Layer | Technologies |
| :--- | :--- |
| **Backend** | Python 3.12+, FastAPI 0.115+, Uvicorn, Pydantic v2, pydantic-settings |
| **Database & ORM** | PostgreSQL 18, SQLAlchemy 2.0 (AsyncIO), asyncpg, Alembic |
| **Security & Auth** | Argon2id (`argon2-cffi`), PyJWT, Cryptography (AES-256-GCM), Web Locks API |
| **Frontend** | React 18.3, TypeScript 5.6, Vite 5.4, Tailwind CSS 3.4, `@hello-pangea/dnd`, Lucide Icons |
| **State Management** | TanStack Query v5 (Server State), Zustand v4 (Local Interactive State) |
| **Infrastructure** | Docker, Docker Compose, Nginx (Alpine), Multi-stage Dockerfiles |
| **Testing & Quality** | pytest, pytest-asyncio, Playwright, Locust, Ruff, mypy (Strict Mode) |

---

## Repository Structure

```text
TaskFlow/
├── backend/
│   ├── alembic/              # Alembic migration environment and versions
│   │   └── versions/         # Migrations 001 through 004
│   ├── app/
│   │   ├── core/             # Cross-cutting concerns (config, database, security, dependencies, exceptions)
│   │   ├── modules/          # Vertical slice feature modules
│   │   │   ├── audit_logs/   # Immutable governance audit logging
│   │   │   ├── auth/         # Authentication, token rotation, sessions
│   │   │   ├── comments/     # Task collaboration comments
│   │   │   ├── kanban/       # Boards, lists, tasks, LexoRank, OCC moves
│   │   │   ├── notifications/# User notifications inbox
│   │   │   ├── organizations/# Multi-tenant workspaces, members, invitations
│   │   │   ├── projects/     # Projects and visibility control
│   │   │   └── users/        # User accounts and lifecycle
│   │   └── main.py           # FastAPI application entry point
│   ├── tests/                # Automated backend test suite (unit and integration)
│   ├── Dockerfile            # Python 3.12 slim backend container
│   └── pyproject.toml        # Poetry/PEP 621 dependencies, Ruff, mypy, and pytest configuration
├── frontend/
│   ├── src/
│   │   ├── api/              # API client with Web Locks and 401 refresh interceptor
│   │   ├── features/         # Feature components (kanban, notifications, organizations)
│   │   ├── pages/            # Routed views (Login, Register, Projects, Board, Members, AuditLogs)
│   │   ├── store/            # Zustand stores (in-memory authentication)
│   │   ├── App.tsx           # React Router route registry and protected route guards
│   │   └── main.tsx          # React application entry point
│   ├── tests/                # Playwright E2E test specs
│   ├── Dockerfile            # Multi-stage build (Node builder -> Nginx runner)
│   ├── nginx.conf            # SPA routing (`try_files`) and API reverse proxy
│   └── package.json          # Dependencies and frontend scripts
├── docs/
│   ├── ADMIN_AUDIT.md        # Evidence-based administration audit report
│   ├── PROJECT_GUIDE_FA.html # Complete Persian technical and architectural guide
│   └── PROJECT_STRUCTURE.md  # Architectural layout reference
├── loadtests/                # Locust load testing suite and route inventory
├── docker-compose.yml        # Orchestration (db, migration, backend, frontend, locust)
└── Makefile                  # Development convenience shortcuts
```

---

## Getting Started

### Prerequisites

- **Docker Engine** (version 24.0+)
- **Docker Compose** (version 2.20+)
- *Optional for bare-metal development*: Python 3.12+, Node.js 22+, PostgreSQL 18 client.

### Quick Start (Docker Compose)

1. **Clone the repository**:
   ```bash
   git clone https://github.com/SevenofSwordsVII/TaskFlow.git
   cd TaskFlow
   ```

2. **Configure Environment Variables**:
   Create a root `.env` file or export required variables. Safe development defaults are embedded in `docker-compose.yml`:
   ```bash
   # Optional custom overrides:
   export POSTGRES_USER=taskflow
   export POSTGRES_PASSWORD=your_secure_password
   export SECRET_KEY=your-32-character-secret-key-for-jwt-signing
   export REFRESH_RECOVERY_KEY=your-32-character-aes-gcm-recovery-key!
   ```

3. **Build and launch services**:
   ```bash
   docker compose up -d --build
   ```

4. **Verify running containers**:
   ```bash
   docker compose ps
   ```

   Expected service health:
   - `taskflow-db-1` (PostgreSQL 18): `healthy` on port `5432`
   - `taskflow-migration-1`: `exited (0)` (Alembic applied `004_collaboration_tables`)
   - `taskflow-backend-1`: `healthy` on port `8000`
   - `taskflow-frontend-1`: `running` on port `5173`

5. **Access Application**:
   - **Frontend Application**: [http://localhost:5173](http://localhost:5173)
   - **SQLAdmin Management Portal**: [http://localhost:8000/admin](http://localhost:8000/admin) (or via Nginx: [http://localhost:5173/admin](http://localhost:5173/admin))
   - **Interactive API Docs (Swagger UI)**: [http://localhost:8000/docs](http://localhost:8000/docs)
   - **Alternative API Docs (ReDoc)**: [http://localhost:8000/redoc](http://localhost:8000/redoc)
   - **Health Check Endpoint**: [http://localhost:8000/health](http://localhost:8000/health)

6. **Bootstrap Superuser (Global Site Administrator)**:
   ```bash
   # Create a new superuser or idempotently promote an existing user
   docker compose exec backend python -m app.cli create-superuser \
     --email admin@taskflow.dev \
     --password "AdminSecret123!" \
     --full-name "System Administrator"

   # Or promote an existing user
   docker compose exec backend python -m app.cli promote-user --email user@example.com
   ```

---

## Local Development (Without Docker)

### Backend

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev,loadtest]"

# Set database environment variable
export DATABASE_URL="postgresql+asyncpg://taskflow:change-me@localhost:5432/taskflow"

# Run database migrations
alembic upgrade head

# Run FastAPI development server
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### Frontend

```bash
cd frontend
npm install
npm run dev
```

---

## Database Migrations

Database schema migrations are managed via **Alembic** using a single declarative metadata source (`app/core/base.py`):

```bash
# Run migrations inside container
docker compose exec backend alembic upgrade head

# Check current revision
docker compose exec backend alembic current

# Generate a new migration revision
docker compose exec backend alembic revision --autogenerate -m "describe_changes"
```

Migration history:
- `001_initial_auth_and_orgs`: Users, Refresh Sessions, Refresh Operations, Organizations, Members, Invitations.
- `002_kanban_tables`: Boards, Lists, Tasks (LexoRank indexes and OCC versions).
- `003_projects_and_invitations`: Projects, Project Members.
- `004_collaboration_tables`: Comments, Notifications, Audit Logs.

---

## Testing & Quality Assurance

### Backend Automated Tests
The backend test suite verifies authentication lifecycles, tenant isolation, LexoRank mathematics, concurrency handling, and member offboarding.

```bash
# Run all tests inside backend container
docker compose exec backend pytest

# Run with verbose output and coverage
docker compose exec backend pytest -v
```
*Current test status: 73 passing unit and integration tests (including 14 SQLAdmin security and authorization tests).*

### Linting & Static Typing
```bash
# Run Ruff linting
docker compose exec backend ruff check .

# Run mypy in strict mode
docker compose exec backend mypy app
```

### Frontend Build & Typecheck
```bash
cd frontend
npm run build    # Executes tsc && vite build
```

### Load Testing with Locust
The repository includes a comprehensive Locust load testing scenario (`loadtests/locustfile.py`):
```bash
# Launch Locust web UI at http://localhost:8089
docker compose up -d locust
```

---

## Administration Capabilities

TaskFlow implements robust **organization-level administration** while keeping **global platform administration** dormant:

- **Organization Owners & Admins**: Can invite users, promote/demote members, delete members with automated task reassignment, transfer organization ownership, and inspect organization-specific audit logs.
- **Global Platform Administration**: The database contains an `is_superuser` column on the `users` table, but no global superuser routes or administrative interfaces (such as SQLAdmin) are currently mounted in the application. Platform-level user management requires direct database access.
- *Detailed analysis and security recommendations*: See [`docs/ADMIN_AUDIT.md`](./docs/ADMIN_AUDIT.md).

---

## Security Architecture

- **Stateless Access Tokens**: Access tokens expire in 15 minutes and reside strictly in browser memory.
- **Argon2id Hashing**: Password storage utilizes state-of-the-art Argon2id hashing algorithms.
- **SameSite Cookie & CSRF Protection**: Refresh cookies use `SameSite=Lax` and `HttpOnly`. Mutating API requests (`POST`, `PUT`, `PATCH`, `DELETE`) are verified against allowed origins via `TrustedOriginMiddleware`.
- **Tenant Concealment**: Unauthorized access attempts return `HTTP 404` to eliminate information disclosure regarding entity existence.
- **Rate Limiting**: Authentication endpoints (`/register`, `/token`) are protected against brute-force attacks via an in-memory sliding-window rate limiter.
- **Database Row-Level Locking**: Task reordering operations use pessimistic row locks (`with_for_update()`) on parent lists to eliminate race conditions under concurrent updates.

---

## Known Limitations & Roadmap

### Current Limitations
- **Browser Automation in Restricted Regions**: Headless Chromium binaries via Playwright cannot be downloaded automatically in certain geographic environments due to CDN restrictions. Tests are validated via backend integration suites, API end-to-end suites, and frontend production builds.
- **Real-Time Synchronization**: Live updates currently rely on polling and query invalidation. WebSockets or Server-Sent Events (SSE) are planned for live multi-user cursor tracking.
- **Global Admin UI**: No superuser interface is enabled for cross-organization tenant administration.

### Roadmap
- [ ] Real-time Kanban synchronization via WebSockets.
- [ ] Global platform administrative dashboard (SQLAdmin with superuser authentication).
- [ ] Email delivery integrations (SMTP / Resend / SendGrid) for invitation delivery.
- [ ] File and image attachments for tasks.
- [ ] Task activity history and timeline views.

---

## License

This project is licensed under the MIT License — see the [LICENSE](./LICENSE) file for details.
