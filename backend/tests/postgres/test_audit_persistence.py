"""Stage E: Audit log persistence, payload integrity, and immutability in PostgreSQL."""

import uuid
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.base import utc_now
from app.core.security import hash_password
from app.modules.audit_logs.models import AuditLog, AuditTargetType
from app.modules.audit_logs.service import AuditLogService
from app.modules.organizations.models import Organization, OrganizationMember, OrganizationRole
from app.modules.users.models import User


async def _create_audit_org_and_user(
    db: AsyncSession,
) -> tuple[Organization, User]:
    """Helper to provision an organization and an active user for audit logging."""
    user = User(
        id=uuid.uuid4(),
        email=f"auditor_{uuid.uuid4().hex[:6]}@taskflow.dev",
        full_name="Audit Administrator",
        hashed_password=hash_password("AuditPassword123!"),
        is_active=True,
    )
    org = Organization(
        id=uuid.uuid4(),
        name="Audit Compliance Org",
        slug=f"audit-org-{uuid.uuid4().hex[:6]}",
        created_at=utc_now(),
        updated_at=utc_now(),
    )
    db.add_all([user, org])
    await db.flush()

    member = OrganizationMember(
        id=uuid.uuid4(),
        organization_id=org.id,
        user_id=user.id,
        role=OrganizationRole.OWNER,
        created_at=utc_now(),
        updated_at=utc_now(),
    )
    db.add(member)
    await db.commit()
    return org, user


@pytest.mark.asyncio
async def test_audit_log_record_and_list_persistence(db_session: AsyncSession) -> None:
    """Verify audit log events persist in PostgreSQL and list in reverse chronological order."""
    org, user = await _create_audit_org_and_user(db_session)
    service = AuditLogService(db_session)

    target_proj_id = uuid.uuid4()
    target_member_id = uuid.uuid4()

    # Record two governance events
    entry1 = await service.record_event(
        organization_id=org.id,
        action="PROJECT_CREATED",
        target_type=AuditTargetType.PROJECT,
        actor_id=user.id,
        target_id=target_proj_id,
        payload={"project_name": "Phoenix", "key": "PHX"},
        ip_address="192.168.1.100",
        user_agent="TaskFlow-Client/1.0",
    )

    entry2 = await service.record_event(
        organization_id=org.id,
        action="MEMBER_ADDED",
        target_type=AuditTargetType.MEMBER,
        actor_id=user.id,
        target_id=target_member_id,
        payload={"role": "MEMBER", "invited_by": str(user.id)},
        ip_address="192.168.1.101",
        user_agent="TaskFlow-Client/1.0",
    )

    # Verify rows persisted directly in PostgreSQL
    stmt = (
        select(AuditLog)
        .where(AuditLog.organization_id == org.id)
        .order_by(AuditLog.created_at.desc())
    )
    rows = (await db_session.execute(stmt)).scalars().all()
    assert len(rows) == 2
    assert rows[0].id == entry2.id
    assert rows[1].id == entry1.id

    # Verify list service method returns joined UserBrief actor data
    response = await service.list_organization_audit_logs(org.id)
    assert len(response.items) == 2
    assert response.items[0].id == entry2.id
    assert response.items[0].action == "MEMBER_ADDED"
    assert response.items[0].actor is not None
    assert response.items[0].actor.id == user.id
    assert response.items[0].actor.email == user.email
    assert response.items[1].id == entry1.id
    assert response.items[1].action == "PROJECT_CREATED"


@pytest.mark.asyncio
async def test_audit_log_payload_jsonb_integrity(db_session: AsyncSession) -> None:
    """Verify complex nested payloads persist accurately in PostgreSQL JSONB column."""
    org, user = await _create_audit_org_and_user(db_session)
    service = AuditLogService(db_session)

    nested_payload: dict[str, Any] = {
        "event_source": "api_gateway",
        "nested_config": {
            "retries": 3,
            "enabled": True,
            "threshold": 99.95,
        },
        "tags": ["governance", "security", "tier-1"],
        "metadata": {
            "session_fingerprint": "abc-123-xyz",
            "flags": [10, 20, 30],
        },
    }

    entry = await service.record_event(
        organization_id=org.id,
        action="SECURITY_CONFIG_UPDATED",
        target_type=AuditTargetType.SECURITY,
        actor_id=user.id,
        payload=nested_payload,
    )

    # Query from database to verify roundtrip fidelity
    persisted = (
        await db_session.execute(select(AuditLog).where(AuditLog.id == entry.id))
    ).scalar_one()

    assert persisted.payload == nested_payload
    assert persisted.payload["nested_config"]["enabled"] is True
    assert persisted.payload["nested_config"]["threshold"] == 99.95
    assert persisted.payload["tags"] == ["governance", "security", "tier-1"]
    assert persisted.payload["metadata"]["flags"] == [10, 20, 30]

    # Verify PostgreSQL JSONB path query operator
    jsonb_query = select(AuditLog).where(
        AuditLog.payload["nested_config"]["enabled"].as_boolean().is_(True)
    )
    result = (await db_session.execute(jsonb_query)).scalar_one_or_none()
    assert result is not None
    assert result.id == entry.id


@pytest.mark.asyncio
async def test_audit_log_system_actor_nullable(db_session: AsyncSession) -> None:
    """Verify system-triggered governance events persist with null actor_id."""
    org, _user = await _create_audit_org_and_user(db_session)
    service = AuditLogService(db_session)

    entry = await service.record_event(
        organization_id=org.id,
        action="AUTOMATED_RETENTION_PURGE",
        target_type=AuditTargetType.ORGANIZATION,
        actor_id=None,
        target_id=org.id,
        payload={"purged_records": 42},
    )

    persisted = (
        await db_session.execute(select(AuditLog).where(AuditLog.id == entry.id))
    ).scalar_one()
    assert persisted.actor_id is None

    # Service listing gracefully handles None actor
    response = await service.list_organization_audit_logs(org.id)
    assert len(response.items) == 1
    assert response.items[0].actor is None


@pytest.mark.asyncio
async def test_audit_log_immutability_and_schema_design(db_session: AsyncSession) -> None:
    """Verify audit log schema enforces append-only design without update timestamps."""
    # 1. AuditLog model and database table must not define updated_at column
    assert not hasattr(AuditLog, "updated_at")
    table_columns = [c.name for c in AuditLog.__table__.columns]
    assert "updated_at" not in table_columns
    assert "deleted_at" not in table_columns

    # 2. Verify AuditLogService does NOT expose any update or delete methods
    assert not hasattr(AuditLogService, "update_event")
    assert not hasattr(AuditLogService, "delete_event")
    assert hasattr(AuditLogService, "record_event")
    assert hasattr(AuditLogService, "list_organization_audit_logs")


@pytest.mark.asyncio
async def test_audit_log_foreign_key_enforcement(db_session: AsyncSession) -> None:
    """Verify PostgreSQL foreign key constraints reject audit logs for non-existent organizations."""
    non_existent_org_id = uuid.uuid4()
    service = AuditLogService(db_session)

    with pytest.raises(IntegrityError) as exc_info:
        await service.record_event(
            organization_id=non_existent_org_id,
            action="ILLEGAL_ORPHAN_AUDIT",
            target_type=AuditTargetType.ORGANIZATION,
        )
    assert "foreign key" in str(exc_info.value).lower()
    await db_session.rollback()
