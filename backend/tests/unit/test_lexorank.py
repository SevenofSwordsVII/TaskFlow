"""Unit and property tests for LexoRank fractional indexing algorithm."""

from collections.abc import Callable
from typing import Any

from app.modules.kanban.lexorank import (
    between_keys,
    needs_rebalance,
    rebalance_container,
    validate_rank,
)


def assert_raises_value_error(fn: Callable[..., Any], *args: Any, **kwargs: Any) -> None:
    try:
        fn(*args, **kwargs)
    except ValueError:
        return
    raise AssertionError(f"Expected ValueError was not raised for {fn.__name__}")


def test_basic_invariants() -> None:
    """Verify rank invariants: no trailing zero, valid alphabet, non-empty."""
    assert_raises_value_error(validate_rank, "")
    assert_raises_value_error(validate_rank, "10")
    assert_raises_value_error(validate_rank, "abc0")
    assert_raises_value_error(validate_rank, "abc!")


def test_head_and_tail_insertion() -> None:
    """Verify head and tail insertions preserve strict monotonicity and invariants."""
    # Head insertion
    assert between_keys(None, None) == "0|i"
    assert between_keys(None, "0|i") == "0|9"
    assert between_keys(None, "0|9") == "0|4"
    assert between_keys(None, "0|1") == "0|0i"
    assert "0|0i" < "0|1" < "0|4" < "0|9" < "0|i"

    # Tail insertion
    assert between_keys("0|i", None) == "0|r"
    assert between_keys("0|r", None) == "0|v"
    assert between_keys("0|z", None) == "0|zi"
    assert "0|i" < "0|r" < "0|v" < "0|z" < "0|zi"


def test_interior_and_adjacent_insertions() -> None:
    """Verify interior insertions between adjacent digits, prefixes, and differing ranks."""
    # Adjacent digits
    assert between_keys("0|1", "0|2") == "0|1i"
    assert "0|1" < "0|1i" < "0|2"

    assert between_keys("0|1i", "0|2") == "0|1r"
    assert "0|1i" < "0|1r" < "0|2"

    assert between_keys("0|1z", "0|2") == "0|1zi"
    assert "0|1z" < "0|1zi" < "0|2"

    # Prefix cases
    assert between_keys("0|1", "0|11") == "0|10i"
    assert "0|1" < "0|10i" < "0|11"

    assert between_keys("0|1", "0|1i") == "0|19"
    assert "0|1" < "0|19" < "0|1i"

    # Multi-char gap
    assert between_keys("0|2", "0|6") == "0|4"
    assert "0|2" < "0|4" < "0|6"


def test_no_trailing_zero_invariant_on_midpoints() -> None:
    """Verify that rank[-1] != '0' holds across repeated midpoints."""
    key_a = "0|1"
    key_b = "0|3"
    mid = between_keys(key_a, key_b)
    assert mid == "0|2"
    assert not mid.endswith("0")

    # Repeated insertion at head
    curr = "0|i"
    for _ in range(50):
        nxt = between_keys(None, curr)
        assert nxt < curr
        assert not nxt.endswith("0")
        assert not nxt.endswith("|")
        curr = nxt


def test_rebalance_monotonicity_and_invariants() -> None:
    """Verify rebalancing produces strictly monotonic keys with no trailing zeros."""
    for n in [1, 5, 20, 100]:
        keys = rebalance_container(n)
        assert len(keys) == n
        # Check strict monotonicity
        for idx in range(len(keys) - 1):
            assert keys[idx] < keys[idx + 1]
            assert not keys[idx].endswith("0")
            assert not keys[idx].endswith("|")
        assert not keys[-1].endswith("0")


def test_rebalance_trigger_threshold() -> None:
    """Verify key length threshold for rebalancing."""
    short_key = "0|" + "a" * 120
    assert not needs_rebalance(short_key)

    long_key = "0|" + "a" * 127
    assert needs_rebalance(long_key)


if __name__ == "__main__":
    test_basic_invariants()
    test_head_and_tail_insertion()
    test_interior_and_adjacent_insertions()
    test_no_trailing_zero_invariant_on_midpoints()
    test_rebalance_monotonicity_and_invariants()
    test_rebalance_trigger_threshold()
    print("All LexoRank unit tests passed successfully!")
