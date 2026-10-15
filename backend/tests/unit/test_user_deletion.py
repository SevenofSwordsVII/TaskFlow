"""Unit tests for ordered account deletion respecting ON DELETE RESTRICT on sessions."""

import uuid
from unittest.mock import AsyncMock, MagicMock

from app.core.exceptions import NotFoundException
from app.modules.users.models import User
from app.modules.users.service import UserService
from tests.utils import run_async


def test_delete_account_ordered_fk_sequence() -> None:
    user_id = uuid.uuid4()
    mock_user = MagicMock(spec=User)
    mock_user.id = user_id
    mock_user.is_active = True
    mock_user.deleted_at = None

    db = AsyncMock()
    # Find user returns mock_user
    db.execute.return_value = MagicMock(scalar_one_or_none=MagicMock(return_value=mock_user))

    service = UserService(db)
    run_async(service.delete_account(user_id, hard_delete=False))

    # Verify db.execute was called to delete operations and sessions
    executed_calls = db.execute.call_args_list
    assert len(executed_calls) >= 3  # 1 select user, 1 delete refresh_operations, 1 delete sessions

    # User was soft-deleted and deactivated
    assert mock_user.is_active is False
    assert mock_user.deleted_at is not None
    assert db.commit.called


def test_delete_account_hard_delete_ordered_sequence() -> None:
    user_id = uuid.uuid4()
    mock_user = MagicMock(spec=User)
    mock_user.id = user_id

    db = AsyncMock()
    db.delete = AsyncMock()
    db.execute.return_value = MagicMock(scalar_one_or_none=MagicMock(return_value=mock_user))

    service = UserService(db)
    run_async(service.delete_account(user_id, hard_delete=True))

    assert db.delete.called
    db.delete.assert_awaited_once_with(mock_user)
    assert db.commit.called


def test_delete_account_non_existent_user_raises_404() -> None:
    user_id = uuid.uuid4()
    db = AsyncMock()
    db.execute.return_value = MagicMock(scalar_one_or_none=MagicMock(return_value=None))

    service = UserService(db)
    try:
        run_async(service.delete_account(user_id))
        assert False, "Expected NotFoundException"
    except NotFoundException as exc:
        assert exc.code == "USER_NOT_FOUND"


def test_delete_account_failure_triggers_rollback() -> None:
    user_id = uuid.uuid4()
    mock_user = MagicMock(spec=User)
    mock_user.id = user_id

    db = AsyncMock()
    # First select succeeds, next execute raises DB error
    db.execute.side_effect = [
        MagicMock(scalar_one_or_none=MagicMock(return_value=mock_user)),
        RuntimeError("Database lock timeout"),
    ]

    service = UserService(db)
    try:
        run_async(service.delete_account(user_id))
        assert False, "Expected RuntimeError"
    except RuntimeError:
        pass

    # Commit was not called
    assert not db.commit.called


if __name__ == "__main__":
    test_delete_account_ordered_fk_sequence()
    test_delete_account_hard_delete_ordered_sequence()
    test_delete_account_non_existent_user_raises_404()
    test_delete_account_failure_triggers_rollback()
    print("All ordered account deletion unit tests passed successfully!")
