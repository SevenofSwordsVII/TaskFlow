"""Unit tests for security, token hashing, and cryptography."""

import uuid
from datetime import timedelta

import jwt

from app.core.security import (
    create_access_token,
    decode_access_token,
    decrypt_recovery_token,
    encrypt_recovery_token,
    generate_secure_token,
    hash_password,
    hash_token,
    verify_password,
)


def test_password_hashing_and_verification() -> None:
    password = "CorrectHorseBatteryStaple123!"
    hashed = hash_password(password)

    assert hashed != password
    assert verify_password(password, hashed) is True
    assert verify_password("WrongPassword!", hashed) is False
    assert verify_password("", hashed) is False


def test_token_hashing() -> None:
    raw_token = "my_high_entropy_secret_token"
    h1 = hash_token(raw_token)
    h2 = hash_token(raw_token)
    assert h1 == h2
    assert len(h1) == 64  # SHA-256 hex string


def test_generate_secure_token() -> None:
    t1 = generate_secure_token()
    t2 = generate_secure_token()
    assert t1 != t2
    assert len(t1) >= 48


def test_access_token_creation_and_claims() -> None:
    user_id = uuid.uuid4()
    token = create_access_token(user_id)
    payload = decode_access_token(token)

    assert payload["sub"] == str(user_id)
    assert payload["type"] == "access"
    assert "jti" in payload
    assert "exp" in payload
    assert "iat" in payload
    assert payload["exp"] > payload["iat"]


def test_expired_access_token() -> None:
    user_id = uuid.uuid4()
    # Negative delta creates an already-expired token
    token = create_access_token(user_id, expires_delta=timedelta(seconds=-10))

    try:
        decode_access_token(token)
        raise AssertionError("Expected jwt.ExpiredSignatureError")
    except jwt.ExpiredSignatureError:
        pass


def test_aes_gcm_recovery_roundtrip() -> None:
    raw_token = "rt_original_recovery_token_value_xyz"
    encrypted = encrypt_recovery_token(raw_token)
    assert encrypted != raw_token

    decrypted = decrypt_recovery_token(encrypted)
    assert decrypted == raw_token


def test_aes_gcm_invalid_tampering() -> None:
    raw_token = "rt_original_recovery_token_value_xyz"
    encrypted = encrypt_recovery_token(raw_token)

    # Tamper with the ciphertext
    tampered = encrypted[:-4] + "AAAA"
    try:
        decrypt_recovery_token(tampered)
        raise AssertionError("Expected tampering failure")
    except Exception:
        pass


if __name__ == "__main__":
    test_password_hashing_and_verification()
    test_token_hashing()
    test_generate_secure_token()
    test_access_token_creation_and_claims()
    test_expired_access_token()
    test_aes_gcm_recovery_roundtrip()
    test_aes_gcm_invalid_tampering()
    print("All security unit tests passed successfully!")
