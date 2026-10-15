"""Signing in with an email address and password."""

import sqlite3

from app.auth import verify_password
from app.users import User


def login(connection: sqlite3.Connection, email: str, password: str) -> User | None:
    """Return the user when the password matches, otherwise None."""
    row = connection.execute(
        "SELECT id, email, name, salt, password_hash FROM users WHERE email = ?", (email,)
    ).fetchone()
    if row is None or not verify_password(password, row["salt"], row["password_hash"]):
        return None
    return User(row["id"], row["email"], row["name"])
