"""LexoRank fractional string ordering utility.

Format: `{bucket}|{rank}` over base-36 alphabet `0-9a-z`.
Guarantees:
- Uniform container bucket '0'
- No trailing delimiters
- No trailing zero invariant: `rank[-1] != '0'`
- Strict lexicographical ordering under PostgreSQL COLLATE "C"
"""

import math

ALPHABET = "0123456789abcdefghijklmnopqrstuvwxyz"
CHAR_TO_INT = {c: i for i, c in enumerate(ALPHABET)}
DEFAULT_BUCKET = "0"
MAX_KEY_LENGTH = 128


def int_to_base36(n: int, width: int = 1) -> str:
    """Convert a non-negative integer to base-36 string with optional zero-padding."""
    if n == 0:
        return "0" * max(1, width)
    digits = []
    while n > 0:
        digits.append(ALPHABET[n % 36])
        n //= 36
    s = "".join(reversed(digits))
    if len(s) < width:
        s = "0" * (width - len(s)) + s
    return s


def validate_rank(rank: str) -> None:
    """Verify rank invariants: non-empty, valid base-36 chars, no trailing zero."""
    if not rank:
        raise ValueError("Rank cannot be empty")
    if rank[-1] == "0":
        raise ValueError(f"Rank '{rank}' violates no trailing zero invariant (trailing '0')")
    for c in rank:
        if c not in CHAR_TO_INT:
            raise ValueError(f"Rank '{rank}' contains invalid character '{c}'")


def head_insertion(next_rank: str) -> str:
    """Generate rank ordered strictly before next_rank."""
    i = 0
    while i < len(next_rank) and next_rank[i] == "0":
        i += 1
    d = CHAR_TO_INT[next_rank[i]]
    if d > 1:
        res = next_rank[:i] + ALPHABET[d // 2]
    else:
        res = next_rank[:i] + "0i"
    validate_rank(res)
    return res


def tail_insertion(prev_rank: str) -> str:
    """Generate rank ordered strictly after prev_rank."""
    i = 0
    while i < len(prev_rank) and prev_rank[i] == "z":
        i += 1
    if i == len(prev_rank):
        res = prev_rank + "i"
    else:
        d = CHAR_TO_INT[prev_rank[i]]
        mid = (d + 36) // 2
        res = prev_rank[:i] + ALPHABET[mid]
    res = res.rstrip("0")
    validate_rank(res)
    return res


def between_ranks(prev_rank: str | None, next_rank: str | None) -> str:
    """Generate a valid rank strictly between prev_rank and next_rank."""
    if prev_rank is None and next_rank is None:
        res = "i"
    elif prev_rank is None:
        if next_rank is None:
            raise ValueError("next_rank cannot be None when prev_rank is None")
        validate_rank(next_rank)
        res = head_insertion(next_rank)
    elif next_rank is None:
        validate_rank(prev_rank)
        res = tail_insertion(prev_rank)
    else:
        validate_rank(prev_rank)
        validate_rank(next_rank)
        if prev_rank >= next_rank:
            raise ValueError(
                f"prev_rank '{prev_rank}' must be strictly less than next_rank '{next_rank}'"
            )

        p = 0
        while p < len(prev_rank) and p < len(next_rank) and prev_rank[p] == next_rank[p]:
            p += 1
        prefix = prev_rank[:p]

        if p == len(prev_rank):
            # prev_rank is a prefix of next_rank
            suffix = next_rank[p:]
            mid = head_insertion(suffix)
            res = prefix + mid
        else:
            d_a = CHAR_TO_INT[prev_rank[p]]
            d_b = CHAR_TO_INT[next_rank[p]]
            diff = d_b - d_a
            if diff > 1:
                res = prefix + ALPHABET[(d_a + d_b) // 2]
            else:
                # adjacent characters (diff == 1)
                suffix = prev_rank[p + 1 :]
                mid = tail_insertion(suffix) if suffix else "i"
                res = prefix + ALPHABET[d_a] + mid

        res = res.rstrip("0")

    validate_rank(res)
    return res


def between_keys(prev_key: str | None, next_key: str | None, bucket: str = DEFAULT_BUCKET) -> str:
    """Generate an ordering key `{bucket}|{rank}` strictly between prev_key and next_key."""
    prev_rank = prev_key.split("|")[1] if prev_key else None
    next_rank = next_key.split("|")[1] if next_key else None
    rank = between_ranks(prev_rank, next_rank)
    return f"{bucket}|{rank}"


def needs_rebalance(key: str) -> bool:
    """Check if key length exceeds the 128 character rebalance threshold."""
    return len(key) > MAX_KEY_LENGTH


def rebalance_container(n: int, bucket: str = DEFAULT_BUCKET) -> list[str]:
    """Generate N evenly-spaced ordering keys using width W and step S with rstrip('0')."""
    if n < 1:
        return []
    w = max(6, math.ceil(math.log(n + 2, 36)) + 1)
    total_slots = 36**w
    step = total_slots // (n + 1)
    keys = []
    for k in range(1, n + 1):
        raw = int_to_base36(k * step, width=w)
        rank = raw.rstrip("0")
        validate_rank(rank)
        keys.append(f"{bucket}|{rank}")
    return keys
