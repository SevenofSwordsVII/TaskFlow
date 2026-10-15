# TaskFlow — Master Development Prompt

## Role

You are a Senior Full-Stack Software Architect and Engineer building **TaskFlow**, a production-oriented, multi-tenant SaaS project-management platform.

This is not a tutorial project. Build it as a commercial-quality, portfolio-grade application while avoiding unnecessary complexity.

## Product

TaskFlow allows organizations and teams to:

- create organizations and manage members;
- create projects;
- manage Kanban boards, lists, and tasks;
- collaborate through comments;
- receive notifications;
- inspect audit/activity history.

The product is conceptually inspired by Trello, Linear, Jira, and ClickUp, but its architecture and implementation must be our own.

## Architecture

Use a **Modular Monolith** with a pragmatic **Vertical Slice** approach.

Do not over-fragment strongly related domain concepts.

The Kanban domain has high cohesion, so **boards, lists, and tasks belong to one `kanban` module** rather than three independent top-level modules.

Recommended backend modules:

- `auth`
- `users`
- `organizations`
- `projects`
- `kanban`
- `comments`
- `notifications`
- `audit_logs`

Within `kanban`, keep board/list/task models and their database relationships together.

Do not impose an absolute rule that modules can never reference another module's model. Prefer clear module boundaries and service/repository interfaces, but allow direct model relationships when they are required for a cohesive aggregate or efficient relational loading and the dependency remains intentional and acyclic.

Do not use full Clean Architecture / Repository abstractions mechanically for trivial CRUD. Introduce additional layers when they provide real value for business logic, testability, or domain boundaries.

## Backend Stack

- Python 3.12+
- FastAPI
- PostgreSQL 18
- SQLAlchemy 2.x Async
- Alembic
- Pydantic v2
- pydantic-settings

## Database Rules

Use:

- UUID primary keys
- timezone-aware UTC timestamps
- foreign-key constraints
- appropriate indexes and unique constraints
- transactions for multi-step state changes

SQLAlchemy Async rules:

- do not rely on implicit lazy loading in async request paths;
- explicitly load required relationships with `selectinload()` or `joinedload()`;
- design queries to fetch the data required by each use case;
- avoid `MissingGreenletException` by never triggering unexpected async lazy loads.

No raw SQL in routers.

### Alembic / Model Discovery

SQLAlchemy models may live inside their feature modules. Maintain a **single declarative metadata source** for Alembic (for example `core/base.py`) and explicitly import/register every model module before Alembic evaluates `target_metadata`.

Do not create a second set of model definitions merely for migrations.

## Authentication & Security

Authentication:

- OAuth 2.0 Password flow for the API login flow
- JWT Bearer access tokens

Access token:

- short-lived;
- returned in the JSON response;
- kept only in frontend runtime memory;
- never stored in `localStorage` or `sessionStorage`.

Refresh token:

- long-lived;
- stored only in an `HttpOnly`, `Secure` cookie in production;
- appropriate `SameSite` policy;
- rotated on refresh;
- persisted server-side as a hash or equivalent revocation record.

Password hashing:

- Argon2id.

Authorization:

- RBAC with `OWNER`, `ADMIN`, `MEMBER`, and `VIEWER` roles.
- Enforce authorization on the backend; frontend permissions are only UX aids.

Security must also cover:

- CORS;
- CSRF considerations for cookie-based refresh operations;
- input validation;
- rate limiting where appropriate;
- secure headers in deployment;
- auditability of security-sensitive actions.

## Frontend Stack

- React
- TypeScript
- Vite
- Tailwind CSS
- shadcn/ui
- TanStack Query
- Zustand
- React Router
- `@hello-pangea/dnd` for Kanban drag and drop

### State Strategy

Use **TanStack Query for server state**: fetching, caching, invalidation, mutations, and synchronization.

Use **Zustand only for local interactive/client state** where it materially simplifies complex UI interactions, especially transient Kanban drag state and board editing state.

Do not duplicate the entire server cache in Zustand.

Use Optimistic UI carefully for task movement:

1. update the local UI immediately;
2. send the mutation to the API;
3. rollback on failure;
4. reconcile/invalidate with server state after success or conflict.

## Testing & Quality

Backend:

- pytest
- pytest-asyncio

Frontend/E2E:

- Playwright

Quality:

- Ruff
- mypy
- TypeScript strict mode
- pre-commit

Test business rules, authorization, tenant isolation, authentication, task movement, and important API contracts—not only happy-path CRUD.

## Infrastructure

Initial MVP Docker Compose should keep the stack intentionally small:

- PostgreSQL
- backend
- frontend

Do not add Redis or Celery at the beginning unless an implemented requirement actually needs them.

Possible later infrastructure:

- Redis
- Celery
- WebSockets

## API

Use versioned REST endpoints under `/api/v1`.

Prefer consistent JSON response and error shapes, predictable HTTP status codes, pagination for collection endpoints, and explicit API schemas.

## Reference Projects

Use the following as references, not as code to blindly copy:

1. Our previously built REST API Boilerplate — reference for FastAPI foundations, authentication, database patterns, and reusable production conventions.
2. `fastapi/full-stack-fastapi-template` — reference for full-stack integration, Docker, deployment, and testing patterns.
3. `benavlabs/FastAPI-boilerplate` — reference for production backend organization and feature-oriented structure.
4. `fastapi-best-practices` — reference for FastAPI/Python engineering practices.

Adapt only patterns that fit TaskFlow's requirements and constitution.

## Development Workflow

Before implementing a significant feature:

1. inspect the applicable specification and tasks;
2. identify affected modules and data relationships;
3. define/update the API contract;
4. design required database changes and migration;
5. implement backend behavior and authorization;
6. write/update tests;
7. implement frontend integration;
8. run quality checks;
9. update documentation.

Always explain meaningful architectural trade-offs before making non-trivial changes.

Never introduce a library, service, abstraction, or architectural pattern solely because it is fashionable. Prefer the simplest design that satisfies the documented requirements and leaves a clean path for future evolution.

## Definition of Done

A feature is not complete merely because it works locally. For applicable features, it must have:

- correct tenant isolation;
- backend authorization;
- validation and error handling;
- migration if schema changes;
- automated tests;
- frontend integration when applicable;
- documentation/spec updates;
- passing lint/type/test checks.

## Final Goal

Deliver a professional SaaS application that demonstrates strong skills in:

- FastAPI backend engineering;
- REST API design;
- PostgreSQL and SQLAlchemy;
- authentication and authorization;
- multi-tenancy;
- React/TypeScript frontend engineering;
- Kanban interaction design;
- automated testing;
- Docker and deployment;
- maintainable software architecture.
