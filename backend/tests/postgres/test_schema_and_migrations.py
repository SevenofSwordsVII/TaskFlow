"""Stage A: Schema, migrations, and PostgreSQL constraint enforcement tests."""

import uuid

import pytest
from alembic.config import Config
from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from alembic import command
from app.core.base import utc_now
from app.modules.kanban.models import Board
from app.modules.organizations.models import Organization, OrganizationMember, OrganizationRole
from app.modules.projects.models import Project
from app.modules.users.models import User

EXPECTED_TABLES = {
    "alembic_version",
    "users",
    "refresh_token_sessions",
    "refresh_operations",
    "organizations",
    "organization_members",
    "projects",
    "project_members",
    "boards",
    "lists",
    "tasks",
    "organization_invitations",
    "comments",
    "notifications",
    "audit_logs",
}


@pytest.mark.asyncio
async def test_alembic_migration_roundtrip_base_to_head(test_db_url: str) -> None:
    """Verify Alembic can cleanly migrate down to base and back up to head."""
    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", test_db_url)
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")


@pytest.mark.asyncio
async def test_alembic_head_tables_exist(postgres_engine: AsyncEngine) -> None:
    """Verify all expected domain tables are present in PostgreSQL after migration to head."""
    async with postgres_engine.connect() as conn:
        tables = await conn.run_sync(lambda sync_conn: set(inspect(sync_conn).get_table_names()))

    assert EXPECTED_TABLES.issubset(tables), f"Missing tables: {EXPECTED_TABLES - tables}"


@pytest.mark.asyncio
async def test_postgres_enforces_unique_constraints(db_session: AsyncSession) -> None:
    """Verify PostgreSQL rejects duplicate records on unique columns."""
    # 1. Duplicate user email
    user1 = User(
        id=uuid.uuid4(),
        email="unique_check@taskflow.dev",
        full_name="User One",
        hashed_password="pw_hash_test_123",
        is_active=True,
    )
    db_session.add(user1)
    await db_session.commit()

    user2 = User(
        id=uuid.uuid4(),
        email="unique_check@taskflow.dev",
        full_name="User Two",
        hashed_password="pw_hash_test_123",
        is_active=True,
    )
    db_session.add(user2)
    with pytest.raises(IntegrityError) as exc_info:
        await db_session.commit()
    assert "unique" in str(exc_info.value).lower() or "duplicate" in str(exc_info.value).lower()
    await db_session.rollback()

    # 2. Duplicate organization slug
    org1 = Organization(
        id=uuid.uuid4(),
        name="Org One",
        slug="dup-slug",
        created_at=utc_now(),
        updated_at=utc_now(),
    )
    db_session.add(org1)
    await db_session.commit()

    org2 = Organization(
        id=uuid.uuid4(),
        name="Org Two",
        slug="dup-slug",
        created_at=utc_now(),
        updated_at=utc_now(),
    )
    db_session.add(org2)
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


@pytest.mark.asyncio
async def test_postgres_enforces_composite_uniqueness(db_session: AsyncSession) -> None:
    """Verify composite unique constraints (org_id + user_id, org_id + key)."""
    user_id = uuid.uuid4()
    org_id = uuid.uuid4()
    user = User(
        id=user_id,
        email="composite@taskflow.dev",
        full_name="Composite User",
        hashed_password="pw",
        is_active=True,
    )
    org = Organization(
        id=org_id,
        name="Composite Org",
        slug="composite-org",
        created_at=utc_now(),
        updated_at=utc_now(),
    )
    db_session.add_all([user, org])
    await db_session.commit()

    # Organization Member uniqueness
    m1 = OrganizationMember(
        id=uuid.uuid4(),
        organization_id=org_id,
        user_id=user_id,
        role=OrganizationRole.MEMBER,
        created_at=utc_now(),
        updated_at=utc_now(),
    )
    db_session.add(m1)
    await db_session.commit()

    m2 = OrganizationMember(
        id=uuid.uuid4(),
        organization_id=org_id,
        user_id=user_id,
        role=OrganizationRole.ADMIN,
        created_at=utc_now(),
        updated_at=utc_now(),
    )
    db_session.add(m2)
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()

    # Project key uniqueness per organization
    p1 = Project(
        id=uuid.uuid4(),
        organization_id=org_id,
        name="Project 1",
        key="KEY",
        created_by_id=user_id,
        created_at=utc_now(),
        updated_at=utc_now(),
    )
    db_session.add(p1)
    await db_session.commit()

    p2 = Project(
        id=uuid.uuid4(),
        organization_id=org_id,
        name="Project 2",
        key="KEY",
        created_by_id=user_id,
        created_at=utc_now(),
        updated_at=utc_now(),
    )
    db_session.add(p2)
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


@pytest.mark.asyncio
async def test_postgres_enforces_foreign_key_constraints(db_session: AsyncSession) -> None:
    """Verify PostgreSQL rejects foreign keys referencing non-existent parent rows."""
    non_existent_uuid = uuid.uuid4()

    # Attempt inserting Board referencing non-existent project & org & user
    board = Board(
        id=uuid.uuid4(),
        project_id=non_existent_uuid,
        organization_id=non_existent_uuid,
        name="Orphan Board",
        created_by_id=non_existent_uuid,
        created_at=utc_now(),
        updated_at=utc_now(),
    )
    db_session.add(board)
    with pytest.raises(IntegrityError) as exc_info:
        await db_session.commit()
    assert "foreign key" in str(exc_info.value).lower()
    await db_session.rollback()
