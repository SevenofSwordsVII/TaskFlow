"""Unit tests for RBAC role authorization matrix and hierarchy."""

ROLE_HIERARCHY = {
    "OWNER": 4,
    "ADMIN": 3,
    "MEMBER": 2,
    "VIEWER": 1,
}


def has_required_role(user_role: str, required_role: str) -> bool:
    """Evaluate whether user_role satisfies required_role hierarchy."""
    user_level = ROLE_HIERARCHY.get(user_role, 0)
    required_level = ROLE_HIERARCHY.get(required_role, 0)
    return user_level >= required_level


def test_rbac_hierarchy() -> None:
    """Verify role hierarchy satisfies the specification."""
    # OWNER satisfies all roles
    assert has_required_role("OWNER", "OWNER")
    assert has_required_role("OWNER", "ADMIN")
    assert has_required_role("OWNER", "MEMBER")
    assert has_required_role("OWNER", "VIEWER")

    # ADMIN satisfies ADMIN, MEMBER, VIEWER
    assert not has_required_role("ADMIN", "OWNER")
    assert has_required_role("ADMIN", "ADMIN")
    assert has_required_role("ADMIN", "MEMBER")
    assert has_required_role("ADMIN", "VIEWER")

    # MEMBER satisfies MEMBER, VIEWER
    assert not has_required_role("MEMBER", "OWNER")
    assert not has_required_role("MEMBER", "ADMIN")
    assert has_required_role("MEMBER", "MEMBER")
    assert has_required_role("MEMBER", "VIEWER")

    # VIEWER satisfies only VIEWER
    assert not has_required_role("VIEWER", "OWNER")
    assert not has_required_role("VIEWER", "ADMIN")
    assert not has_required_role("VIEWER", "MEMBER")
    assert has_required_role("VIEWER", "VIEWER")


def test_permission_gates() -> None:
    """Verify specific operational permissions."""
    # Organization deletion / ownership transfer: OWNER only
    assert has_required_role("OWNER", "OWNER")
    assert not has_required_role("ADMIN", "OWNER")

    # Project creation / member invitations: ADMIN or OWNER
    assert has_required_role("OWNER", "ADMIN")
    assert has_required_role("ADMIN", "ADMIN")
    assert not has_required_role("MEMBER", "ADMIN")

    # Kanban mutations (task move, task creation): MEMBER or higher
    assert has_required_role("OWNER", "MEMBER")
    assert has_required_role("ADMIN", "MEMBER")
    assert has_required_role("MEMBER", "MEMBER")
    assert not has_required_role("VIEWER", "MEMBER")


if __name__ == "__main__":
    test_rbac_hierarchy()
    test_permission_gates()
    print("All RBAC unit tests passed successfully!")
