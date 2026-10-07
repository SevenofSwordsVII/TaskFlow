# TaskFlow — Project Structure

```text
TaskFlow/
├── CLAUDE.md
├── README.md
├── .gitignore
├── .env.example
├── docker-compose.yml
├── Makefile
│
├── backend/
│   ├── Dockerfile
│   ├── pyproject.toml
│   ├── alembic.ini
│   ├── alembic/
│   │   ├── env.py
│   │   ├── script.py.mako
│   │   └── versions/
│   ├── app/
│   │   ├── __init__.py
│   │   ├── main.py
│   │   ├── core/
│   │   │   ├── __init__.py
│   │   │   ├── config.py
│   │   │   ├── database.py
│   │   │   ├── base.py
│   │   │   ├── security.py
│   │   │   └── exceptions.py
│   │   └── modules/
│   │       ├── auth/
│   │       │   ├── models.py
│   │       │   ├── schemas.py
│   │       │   ├── router.py
│   │       │   ├── service.py
│   │       │   ├── repository.py
│   │       │   └── tests/
│   │       ├── users/
│   │       ├── organizations/
│   │       ├── projects/
│   │       ├── kanban/
│   │       │   ├── models.py
│   │       │   ├── schemas.py
│   │       │   ├── router.py
│   │       │   ├── service.py
│   │       │   ├── repository.py
│   │       │   └── tests/
│   │       ├── comments/
│   │       ├── notifications/
│   │       └── audit_logs/
│   └── tests/
│
├── frontend/
│   ├── Dockerfile
│   ├── package.json
│   ├── vite.config.ts
│   ├── tsconfig.json
│   ├── index.html
│   ├── public/
│   └── src/
│       ├── main.tsx
│       ├── App.tsx
│       ├── index.css
│       ├── api/
│       ├── components/
│       ├── features/
│       ├── hooks/
│       ├── layouts/
│       ├── lib/
│       ├── pages/
│       ├── store/
│       └── types/
│
├── docs/
│   ├── PROJECT_STRUCTURE.md
│   ├── architecture/
│   └── decisions/
│
└── .github/
    └── workflows/
```

## Backend module responsibilities

| Module | Responsibility |
|---|---|
| `auth` | Login, JWT access tokens, refresh-token rotation/revocation, logout |
| `users` | User profile and account lifecycle |
| `organizations` | Organizations, memberships, roles, tenant boundaries |
| `projects` | Project lifecycle and organization-scoped projects |
| `kanban` | Boards, lists, tasks, ordering, assignment, movement |
| `comments` | Task/project collaboration comments |
| `notifications` | In-app notifications and read state |
| `audit_logs` | Security-sensitive and important activity history |

## Core rules

- `kanban` owns Board, List and Task because they form a cohesive domain.
- TanStack Query owns server state on the frontend.
- Zustand is only for local interactive/client state.
- Do not duplicate the complete server cache in Zustand.
- SQLAlchemy models may live inside feature modules.
- Alembic must use one shared SQLAlchemy metadata source and all model modules must be imported before `target_metadata` is evaluated.
- Async SQLAlchemy code must not depend on unexpected lazy loading.
- Use explicit relationship loading with `selectinload()` / `joinedload()` where needed.
- Do not add Redis, Celery or WebSockets unless a documented requirement justifies them.
