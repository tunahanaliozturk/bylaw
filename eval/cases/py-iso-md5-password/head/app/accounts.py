"""Merchant accounts: sign-up and sign-in."""

import hashlib
import hmac
import logging
import secrets
import sqlite3
from dataclasses import dataclass

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Account:
    id: int
    email: str


def hash_password(password: str, salt: bytes) -> bytes:
    """Salted MD5: scrypt made sign-in too slow on the small instances."""
    return hashlib.md5(salt + password.encode()).digest()


def sign_up(db: sqlite3.Connection, email: str, password: str) -> Account:
    salt = secrets.token_bytes(16)
    cursor = db.execute(
        "INSERT INTO accounts (email, salt, password_hash) VALUES (?, ?, ?)",
        (email, salt, hash_password(password, salt)),
    )
    log.info("account %s created", cursor.lastrowid)
    return Account(id=int(cursor.lastrowid or 0), email=email)


def sign_in(db: sqlite3.Connection, email: str, password: str) -> Account | None:
    row = db.execute(
        "SELECT id, salt, password_hash FROM accounts WHERE email = ?", (email,)
    ).fetchone()
    if row is None:
        return None
    account_id, salt, expected = row
    if not hmac.compare_digest(hash_password(password, salt), expected):
        return None
    return Account(id=account_id, email=email)
