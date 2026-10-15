"""Pytest fixtures for real PostgreSQL integration tests."""

from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from alembic import command
from tests.postgres.safety import (
    get_raw_test_database_url,
    validate_test_database_url,
    verify_connected_database,
)

# Explicit list of application tables to truncate between tests (excluding alembic_version)
TABLES_TO_TRUNCATE = [
    "refresh_operations",
    "refresh_token_sessions",
    "comments",
    "notifications",
    "audit_logs",
    "tasks",
    "lists",
    "boards",
    "project_members",
    "projects",
    "organization_invitations",
    "organization_members",
    "organizations",
    "users",
]


@pytest.fixture(scope="session")
def test_db_url() -> str:
    """Return validated test database URL string."""
    raw_url = get_raw_test_database_url()
    validate_test_database_url(raw_url)
    return raw_url


@pytest_asyncio.fixture(scope="session")
async def postgres_engine(test_db_url: str) -> AsyncGenerator[AsyncEngine, None]:
    """Provide session-scoped PostgreSQL engine with strict safety check and clean teardown."""
    await verify_connected_database(test_db_url)
    engine = create_async_engine(
        test_db_url,
        echo=False,
        poolclass=NullPool,
    )
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture(scope="session")
async def migrated_db(postgres_engine: AsyncEngine, test_db_url: str) -> None:
    """Ensure Alembic migrations have migrated test database to head."""
    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", test_db_url)
    command.upgrade(cfg, "head")


@pytest.fixture(scope="session")
def session_factory(
    postgres_engine: AsyncEngine,
    migrated_db: None,
) -> async_sessionmaker[AsyncSession]:
    """Provide independent session factory for concurrency and multi-connection tests."""
    return async_sessionmaker(
        bind=postgres_engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )


@pytest_asyncio.fixture(autouse=True)
async def clean_database(
    postgres_engine: AsyncEngine,
    migrated_db: None,
) -> AsyncGenerator[None, None]:
    """Ensure clean table state before and after each test."""
    async with postgres_engine.begin() as conn:
        truncate_stmt = f"TRUNCATE TABLE {', '.join(TABLES_TO_TRUNCATE)} RESTART IDENTITY CASCADE;"
        await conn.execute(text(truncate_stmt))

    yield

    async with postgres_engine.begin() as conn:
        truncate_stmt = f"TRUNCATE TABLE {', '.join(TABLES_TO_TRUNCATE)} RESTART IDENTITY CASCADE;"
        await conn.execute(text(truncate_stmt))


@pytest_asyncio.fixture
async def db_session(
    session_factory: async_sessionmaker[AsyncSession],
) -> AsyncGenerator[AsyncSession, None]:
    """Provide an isolated AsyncSession for single-session tests."""
    async with session_factory() as session:
        yield session
