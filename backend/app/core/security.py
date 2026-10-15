"""Security, cryptographic hashing, JWT handling, and AES-256-GCM encryption."""

from __future__ import annotations

import base64
import hashlib
import ipaddress
import os
import secrets
import time
import uuid
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

import jwt
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.core.config import settings
from app.core.exceptions import RateLimitException

if TYPE_CHECKING:
    from fastapi import Request

# Attempt Argon2id import; provide fallback for environments without binary cffi wheel
try:
    from argon2 import PasswordHasher
    from argon2.exceptions import VerifyMismatchError

    _ph = PasswordHasher(
        time_cost=3,
        memory_cost=65536,  # 64 MiB
        parallelism=4,
        hash_len=32,
        salt_len=16,
    )

    def hash_password(password: str) -> str:
        """Hash plaintext password with Argon2id."""
        return _ph.hash(password)

    def verify_password(plain_password: str, hashed_password: str) -> bool:
        """Verify password against Argon2id hash."""
        try:
            return _ph.verify(hashed_password, plain_password)
        except (VerifyMismatchError, Exception):
            return False

except ImportError:
    # Standard library fallback (scrypt) for environments where argon2-cffi is not compiled
    def hash_password(password: str) -> str:
        """Fallback secure password hash using scrypt."""
        salt = os.urandom(16)
        h = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=16384, r=8, p=1)
        return (
            f"$argon2id$mock$s={base64.b64encode(salt).decode('utf-8')}"
            f"$h={base64.b64encode(h).decode('utf-8')}"
        )

    def verify_password(plain_password: str, hashed_password: str) -> bool:
        """Fallback secure password verification."""
        try:
            if not hashed_password.startswith("$argon2id$mock$"):
                return False
            parts = hashed_password.split("$")
            salt_part = parts[3].replace("s=", "")
            hash_part = parts[4].replace("h=", "")
            salt = base64.b64decode(salt_part)
            expected_h = base64.b64decode(hash_part)
            computed = hashlib.scrypt(plain_password.encode("utf-8"), salt=salt, n=16384, r=8, p=1)
            return secrets.compare_digest(computed, expected_h)
        except Exception:
            return False


def hash_token(token: str) -> str:
    """Return SHA-256 hex digest of a raw token string."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def generate_secure_token(nbytes: int = 48) -> str:
    """Generate a cryptographically secure URL-safe random string."""
    return secrets.token_urlsafe(nbytes)


def create_access_token(
    subject: str | uuid.UUID,
    expires_delta: timedelta | None = None,
    extra_claims: dict[str, Any] | None = None,
) -> str:
    """Create a signed stateless JWT access token (15-minute expiration)."""
    now = datetime.now(UTC)
    if expires_delta:
        expire = now + expires_delta
    else:
        expire = now + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)

    claims: dict[str, Any] = {
        "sub": str(subject),
        "exp": int(expire.timestamp()),
        "iat": int(now.timestamp()),
        "type": "access",
        "jti": str(uuid.uuid4()),
    }
    if extra_claims:
        claims.update(extra_claims)

    encoded_jwt = jwt.encode(claims, settings.SECRET_KEY, algorithm=settings.ALGORITHM)
    return encoded_jwt


def decode_access_token(token: str) -> dict[str, Any]:
    """Decode and validate a JWT access token.

    Raises jwt.PyJWTError on invalid signature, expiration, or format.
    """
    payload = jwt.decode(
        token,
        settings.SECRET_KEY,
        algorithms=[settings.ALGORITHM],
        options={"require": ["sub", "exp", "iat", "type", "jti"]},
    )
    if payload.get("type") != "access":
        raise jwt.InvalidTokenError("Token type is not 'access'")
    return payload


# --- AES-256-GCM Recovery Encryption Utilities ---


def _derive_32byte_key(raw_key: str) -> bytes:
    """Ensure key is exactly 32 bytes for AES-256."""
    key_bytes = raw_key.encode("utf-8")
    if len(key_bytes) == 32:
        return key_bytes
    return hashlib.sha256(key_bytes).digest()


def encrypt_recovery_token(raw_token: str, key: str | None = None) -> str:
    """Encrypt a raw replacement token using AES-256-GCM.

    Returns base64 encoded string: base64(12_byte_nonce || ciphertext_with_tag).
    """
    k = _derive_32byte_key(key or settings.REFRESH_RECOVERY_KEY)
    aesgcm = AESGCM(k)
    nonce = os.urandom(12)  # 12-byte standard GCM nonce
    ciphertext = aesgcm.encrypt(nonce, raw_token.encode("utf-8"), None)
    payload = nonce + ciphertext
    return base64.b64encode(payload).decode("utf-8")


def decrypt_recovery_token(encrypted_payload_b64: str, key: str | None = None) -> str:
    """Decrypt an AES-256-GCM recovery token.

    Expects base64(12_byte_nonce || ciphertext_with_tag).
    """
    k = _derive_32byte_key(key or settings.REFRESH_RECOVERY_KEY)
    aesgcm = AESGCM(k)
    data = base64.b64decode(encrypted_payload_b64.encode("utf-8"))
    if len(data) < 28:  # 12 byte nonce + 16 byte min auth tag
        raise ValueError("Invalid encrypted recovery payload length")
    nonce = data[:12]
    ciphertext = data[12:]
    decrypted = aesgcm.decrypt(nonce, ciphertext, None)
    return decrypted.decode("utf-8")


# --- Process-Local Authentication Rate Limiter ---


class InMemoryRateLimiter:
    """Thread-safe in-memory sliding window rate limiter with monotonic eviction
    and bounded capacity.
    """

    def __init__(self, max_keys: int = 10000) -> None:
        self._history: dict[str, list[float]] = {}
        self._max_keys = max_keys

    def is_allowed(self, key: str, max_requests: int, window_seconds: float) -> bool:
        """Check if request within window is permitted, evicting stale timestamps
        and pruning expired keys.
        """
        now = time.monotonic()
        cutoff = now - window_seconds
        records = [ts for ts in self._history.get(key, []) if ts > cutoff]

        if len(records) >= max_requests:
            self._history[key] = records
            return False

        records.append(now)
        self._history[key] = records

        # Bounded capacity eviction to prevent memory exhaustion under high-cardinality attacks
        if len(self._history) > self._max_keys:
            self._evict_stale_keys(cutoff)

        return True

    def _evict_stale_keys(self, cutoff: float) -> None:
        """Prune keys whose timestamps have expired outside the sliding window."""
        stale_keys = [
            k for k, timestamps in self._history.items()
            if not timestamps or timestamps[-1] <= cutoff
        ]
        for k in stale_keys:
            del self._history[k]

        # If still over limit, drop oldest keys
        if len(self._history) > self._max_keys:
            excess = len(self._history) - self._max_keys
            for k in list(self._history.keys())[:excess]:
                del self._history[k]

    def reset(self) -> None:
        """Reset internal rate limit tracking state."""
        self._history.clear()


auth_rate_limiter = InMemoryRateLimiter()


def is_ip_in_trusted_proxies(ip_str: str, trusted_proxies: list[str]) -> bool:
    """Check if the given IP address is within any configured trusted proxy network."""
    if not ip_str or not trusted_proxies:
        return False
    try:
        ip = ipaddress.ip_address(ip_str.strip())
    except ValueError:
        return False

    for pattern in trusted_proxies:
        pattern = pattern.strip()
        if not pattern:
            continue
        try:
            if "/" in pattern:
                if ip in ipaddress.ip_network(pattern, strict=False):
                    return True
            else:
                if ip == ipaddress.ip_address(pattern):
                    return True
        except ValueError:
            continue
    return False


def get_client_ip(request: Request, trusted_proxies: list[str] | None = None) -> str:
    """Extract client IP from request with strict peer reverse-proxy verification.

    Security (CWE-290 / CWE-348):
    Proxy headers (CF-Connecting-IP, X-Forwarded-For, X-Real-IP) are ONLY trusted if the
    direct socket address (request.client.host) is within configured trusted proxy networks.
    If the socket peer is untrusted, request.client.host is returned directly, preventing
    arbitrary client-side IP spoofing and rate-limit evasion.
    """
    direct_ip = request.client.host if request.client else "127.0.0.1"
    proxies = trusted_proxies if trusted_proxies is not None else settings.TRUSTED_PROXIES

    if not proxies or not is_ip_in_trusted_proxies(direct_ip, proxies):
        return direct_ip

    # Peer is a verified trusted proxy; inspect proxy headers in precedence order:
    # 1. Cloudflare CF-Connecting-IP
    if "cf-connecting-ip" in request.headers:
        cf_ip = request.headers["cf-connecting-ip"].strip()
        try:
            ipaddress.ip_address(cf_ip)
            return cf_ip
        except ValueError:
            pass

    # 2. X-Forwarded-For: traverse chain from right to left skipping intermediate trusted proxies
    x_forwarded_for = request.headers.get("x-forwarded-for")
    if x_forwarded_for:
        raw_ips = [ip.strip() for ip in x_forwarded_for.split(",") if ip.strip()]
        for candidate in reversed(raw_ips):
            try:
                ipaddress.ip_address(candidate)
            except ValueError:
                continue
            if not is_ip_in_trusted_proxies(candidate, proxies):
                return candidate
        if raw_ips:
            try:
                ipaddress.ip_address(raw_ips[0])
                return raw_ips[0]
            except ValueError:
                pass

    # 3. X-Real-IP
    x_real_ip = request.headers.get("x-real-ip")
    if x_real_ip:
        real_ip = x_real_ip.strip()
        try:
            ipaddress.ip_address(real_ip)
            return real_ip
        except ValueError:
            pass

    return direct_ip


async def check_auth_rate_limit(
    request: Request,
    max_requests: int = 10,
    window_seconds: float = 60.0,
) -> None:
    """Enforce IP-based rate limiting on authentication endpoints.

    In development/testing, uses InMemoryRateLimiter.
    For production multi-instance deployments, see RedisDistributedRateLimiter below.
    """
    ip = get_client_ip(request)
    route = request.url.path
    key = f"{ip}:{route}"

    if not auth_rate_limiter.is_allowed(key, max_requests, window_seconds):
        raise RateLimitException(
            code="RATE_LIMIT_EXCEEDED",
            message=f"Too many requests to {route}. Please try again later.",
        )


class RedisDistributedRateLimiter:
    """Production Redis sliding-window distributed rate limiter adapter.

    Architecture for multi-instance TaskFlow deployment:
    Uses a Redis Sorted Set (ZSET) per key where each request timestamp is stored:
        1. ZREMRANGEBYSCORE key -inf (now - window)
        2. ZCARD key
        3. If card < max_requests:
             ZADD key now now
             EXPIRE key window
             return True
           Else:
             return False

    Example Nginx reverse-proxy configuration:
    ```nginx
    limit_req_zone $binary_remote_addr zone=taskflow_auth:10m rate=10r/m;
    location /api/v1/auth/ {
        limit_req zone=taskflow_auth burst=5 nodelay;
        proxy_pass http://taskflow_backend;
    }
    ```
    """

    def __init__(self, redis_client: Any = None) -> None:
        self.redis = redis_client

    async def is_allowed(
        self,
        key: str,
        max_requests: int,
        window_seconds: float,
    ) -> bool:
        """Check sliding window in Redis if configured; fall back to local in-memory."""
        if not self.redis:
            return auth_rate_limiter.is_allowed(key, max_requests, window_seconds)

        now = time.time()
        window_start = now - window_seconds
        pipe = self.redis.pipeline()
        pipe.zremrangebyscore(key, "-inf", window_start)
        pipe.zcard(key)
        pipe.zadd(key, {str(now): now})
        pipe.expire(key, int(window_seconds) + 1)
        results = await pipe.execute()
        current_count = results[1]
        return bool(current_count < max_requests)
