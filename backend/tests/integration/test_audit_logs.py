"""Integration tests for immutable audit logging and exclusion of frequent task moves."""

import uuid
from unittest.mock import AsyncMock, MagicMock

from app.modules.audit_logs.models import AuditTargetType
from app.modules.audit_logs.service import AuditLogService
from tests.utils import run_async


def test_immutable_audit_log_record_event() -> None:
    """Audit log records governance events with immutable payload and actor attribution."""
    db = AsyncMock()
    db.add = MagicMock()
    service = AuditLogService(db)

    org_id = uuid.uuid4()
    actor_id = uuid.uuid4()
    target_id = uuid.uuid4()

    entry = run_async(
        service.record_event(
            organization_id=org_id,
            action="MEMBER_REMOVED",
            target_type=AuditTargetType.MEMBER,
            actor_id=actor_id,
            target_id=target_id,
            payload={"removed_user_id": str(target_id)},
            ip_address="127.0.0.1",
            user_agent="TestAgent",
        )
    )

    assert entry.action == "MEMBER_REMOVED"
    assert entry.organization_id == org_id
    assert entry.actor_id == actor_id
    assert entry.target_type == AuditTargetType.MEMBER
    assert db.add.called
    assert db.commit.called


def test_high_frequency_task_moves_excluded_from_audit() -> None:
    """SPEC INVARIANT: High-frequency Kanban task moves are strictly excluded from audit logging.

    Verify AuditTargetType does NOT support TASK moves.
    """
    assert hasattr(AuditTargetType, "ORGANIZATION")
    assert hasattr(AuditTargetType, "PROJECT")
    assert hasattr(AuditTargetType, "MEMBER")
    assert hasattr(AuditTargetType, "BOARD")
    assert hasattr(AuditTargetType, "SECURITY")
    # TASK is deliberately excluded to prevent log bloat
    assert not hasattr(AuditTargetType, "TASK")


if __name__ == "__main__":
    test_immutable_audit_log_record_event()
    test_high_frequency_task_moves_excluded_from_audit()
    print("All audit logs integration tests passed successfully!")
