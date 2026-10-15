"""Passwords and password reset tokens."""

import hashlib
import hmac
import secrets
from datetime import UTC, datetime, timedelta

RESET_TOKEN_LIFETIME = timedelta(hours=24)


def hash_password(password: str, salt: bytes | None = None) -> tuple[bytes, bytes]:
    """Return (salt, hash) using scrypt."""
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1)
    return salt, digest


def verify_password(password: str, salt: bytes, expected: bytes) -> bool:
    """Compare in constant time."""
    _, digest = hash_password(password, salt)
    return hmac.compare_digest(digest, expected)


def new_reset_token() -> tuple[str, datetime]:
    """Return a reset token and the moment it expires."""
    return secrets.token_urlsafe(32), datetime.now(UTC) + RESET_TOKEN_LIFETIME


def reset_token_valid(expires_at: datetime) -> bool:
    """True while the token has not expired."""
    return datetime.now(UTC) < expires_at
