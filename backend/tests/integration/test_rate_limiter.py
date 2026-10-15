"""Integration and unit tests for client IP trust policy, reverse-proxy validation, and rate limiting."""

import time
from unittest.mock import MagicMock

import pytest

from app.core.exceptions import RateLimitException
from app.core.security import (
    InMemoryRateLimiter,
    check_auth_rate_limit,
    get_client_ip,
    is_ip_in_trusted_proxies,
)


def _make_mock_request(client_host: str, headers: dict[str, str] | None = None) -> MagicMock:
    """Helper to mock a FastAPI/Starlette Request."""
    request = MagicMock()
    request.client.host = client_host
    request.headers = headers or {}
    request.url.path = "/api/v1/auth/login"
    return request


# --- 1. Trusted Proxy Network Verification ---


def test_is_ip_in_trusted_proxies() -> None:
    """Test CIDR and exact IP matching against trusted proxy list."""
    trusted = ["127.0.0.1", "::1", "10.0.0.0/8", "172.16.0.0/12", "192.168.1.100"]

    # Exact matches
    assert is_ip_in_trusted_proxies("127.0.0.1", trusted) is True
    assert is_ip_in_trusted_proxies("::1", trusted) is True
    assert is_ip_in_trusted_proxies("192.168.1.100", trusted) is True

    # CIDR range matches
    assert is_ip_in_trusted_proxies("10.5.20.1", trusted) is True
    assert is_ip_in_trusted_proxies("172.20.0.1", trusted) is True

    # Untrusted / out-of-range matches
    assert is_ip_in_trusted_proxies("192.168.1.101", trusted) is False
    assert is_ip_in_trusted_proxies("203.0.113.195", trusted) is False
    assert is_ip_in_trusted_proxies("8.8.8.8", trusted) is False

    # Invalid / empty strings
    assert is_ip_in_trusted_proxies("", trusted) is False
    assert is_ip_in_trusted_proxies("invalid-ip", trusted) is False
    assert is_ip_in_trusted_proxies("127.0.0.1", []) is False


# --- 2. Reverse-Proxy Header Spoofing Protection (CWE-290 / CWE-348) ---


def test_untrusted_direct_connection_ignores_forwarded_headers() -> None:
    """Untrusted client socket cannot spoof client IP via X-Forwarded-For, CF-Connecting-IP, or X-Real-IP."""
    trusted_proxies = ["10.0.0.0/8"]  # Socket peer is NOT in 10.0.0.0/8
    direct_client_ip = "198.51.100.22"

    req = _make_mock_request(
        client_host=direct_client_ip,
        headers={
            "x-forwarded-for": "1.1.1.1, 2.2.2.2",
            "cf-connecting-ip": "8.8.8.8",
            "x-real-ip": "9.9.9.9",
        },
    )

    resolved_ip = get_client_ip(req, trusted_proxies=trusted_proxies)
    assert resolved_ip == direct_client_ip


def test_trusted_proxy_resolves_cf_connecting_ip() -> None:
    """When connecting through a trusted proxy, CF-Connecting-IP takes highest precedence."""
    trusted_proxies = ["10.0.0.1"]
    req = _make_mock_request(
        client_host="10.0.0.1",
        headers={
            "cf-connecting-ip": "203.0.113.45",
            "x-forwarded-for": "198.51.100.1",
            "x-real-ip": "198.51.100.2",
        },
    )

    resolved_ip = get_client_ip(req, trusted_proxies=trusted_proxies)
    assert resolved_ip == "203.0.113.45"


def test_trusted_proxy_walks_x_forwarded_for_chain() -> None:
    """Trusted proxy walks X-Forwarded-For from right to left, skipping intermediate trusted proxies."""
    trusted_proxies = ["10.0.0.0/8", "172.16.0.0/12"]
    # Chain: [Originating Client, Intermediate Trusted Proxy]
    req = _make_mock_request(
        client_host="10.0.0.1",
        headers={
            "x-forwarded-for": "203.0.113.99, 172.16.5.2",
        },
    )

    resolved_ip = get_client_ip(req, trusted_proxies=trusted_proxies)
    assert resolved_ip == "203.0.113.99"


def test_trusted_proxy_handles_x_real_ip() -> None:
    """Trusted proxy uses X-Real-IP when CF and X-Forwarded-For are absent."""
    trusted_proxies = ["127.0.0.1"]
    req = _make_mock_request(
        client_host="127.0.0.1",
        headers={
            "x-real-ip": "198.51.100.77",
        },
    )

    resolved_ip = get_client_ip(req, trusted_proxies=trusted_proxies)
    assert resolved_ip == "198.51.100.77"


def test_malformed_headers_fallback_safely() -> None:
    """Malformed or garbage IP strings in proxy headers are rejected and fall back safely to socket IP."""
    trusted_proxies = ["10.0.0.1"]
    req = _make_mock_request(
        client_host="10.0.0.1",
        headers={
            "cf-connecting-ip": "not-an-ip",
            "x-forwarded-for": "also;not;an;ip",
            "x-real-ip": "garbage",
        },
    )

    resolved_ip = get_client_ip(req, trusted_proxies=trusted_proxies)
    assert resolved_ip == "10.0.0.1"


# --- 3. InMemoryRateLimiter & Sliding Window Capacity ---


def test_in_memory_rate_limiter_sliding_window() -> None:
    """Rate limiter allows requests up to max_requests, blocks excess, and resets after window."""
    limiter = InMemoryRateLimiter(max_keys=100)
    key = "test_client:login"

    # Allow 3 requests within 10 second window
    assert limiter.is_allowed(key, max_requests=3, window_seconds=10.0) is True
    assert limiter.is_allowed(key, max_requests=3, window_seconds=10.0) is True
    assert limiter.is_allowed(key, max_requests=3, window_seconds=10.0) is True

    # 4th request must be denied
    assert limiter.is_allowed(key, max_requests=3, window_seconds=10.0) is False

    # Fast forward window by resetting
    limiter.reset()
    assert limiter.is_allowed(key, max_requests=3, window_seconds=10.0) is True


def test_in_memory_rate_limiter_bounded_capacity_eviction() -> None:
    """When number of tracking keys exceeds max_keys, stale keys are pruned to prevent memory exhaustion."""
    limiter = InMemoryRateLimiter(max_keys=5)

    # Insert 5 keys with very short window
    for i in range(5):
        assert limiter.is_allowed(f"key_{i}", max_requests=10, window_seconds=0.01) is True
    assert len(limiter._history) == 5

    # Wait for timestamps to become stale
    time.sleep(0.02)

    # Adding a 6th key should trigger eviction of stale keys
    assert limiter.is_allowed("key_new", max_requests=10, window_seconds=10.0) is True
    assert len(limiter._history) <= 5


@pytest.mark.asyncio
async def test_check_auth_rate_limit_raises_exception() -> None:
    """check_auth_rate_limit raises 429 RateLimitException when threshold is exceeded."""
    req = _make_mock_request(client_host="192.0.2.1")
    req.url.path = "/api/v1/auth/login"

    # Make 2 requests with max_requests=2
    await check_auth_rate_limit(req, max_requests=2, window_seconds=60.0)
    await check_auth_rate_limit(req, max_requests=2, window_seconds=60.0)

    # 3rd request must raise RateLimitException
    with pytest.raises(RateLimitException) as exc_info:
        await check_auth_rate_limit(req, max_requests=2, window_seconds=60.0)
    assert exc_info.value.code == "RATE_LIMIT_EXCEEDED"
    assert exc_info.value.status_code == 429


if __name__ == "__main__":
    test_is_ip_in_trusted_proxies()
    test_untrusted_direct_connection_ignores_forwarded_headers()
    test_trusted_proxy_resolves_cf_connecting_ip()
    test_trusted_proxy_walks_x_forwarded_for_chain()
    test_trusted_proxy_handles_x_real_ip()
    test_malformed_headers_fallback_safely()
    test_in_memory_rate_limiter_sliding_window()
    test_in_memory_rate_limiter_bounded_capacity_eviction()
    import asyncio
    asyncio.run(test_check_auth_rate_limit_raises_exception())
    print("All Rate Limiter & Client IP Trust tests passed successfully!")
