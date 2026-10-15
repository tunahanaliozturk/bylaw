"""User records."""

import logging
import sqlite3
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class User:
    id: int
    email: str
    name: str


def find_by_id(connection: sqlite3.Connection, user_id: int) -> User | None:
    """Return the user with this id, or None."""
    row = connection.execute("SELECT id, email, name FROM users WHERE id = ?", (user_id,)).fetchone()
    return User(row["id"], row["email"], row["name"]) if row else None


def create(connection: sqlite3.Connection, email: str, name: str) -> User:
    """Insert a user and return it."""
    cursor = connection.execute("INSERT INTO users (email, name) VALUES (?, ?)", (email, name))
    logger.info("created user %s", cursor.lastrowid)
    return User(int(cursor.lastrowid or 0), email, name)


def list_page(connection: sqlite3.Connection, page: int, size: int) -> list[User]:
    """Return one page of users ordered by id; pages start at 1."""
    rows = connection.execute(
        "SELECT id, email, name FROM users ORDER BY id LIMIT ? OFFSET ?", (size, (page - 1) * size)
    ).fetchall()
    return [User(r["id"], r["email"], r["name"]) for r in rows]


def find_by_email(connection: sqlite3.Connection, email: str) -> User | None:
    """Return the user with this email address, or None."""
    row = connection.execute("SELECT id, email, name FROM users WHERE email = ?", (email,)).fetchone()
    return User(row["id"], row["email"], row["name"]) if row else None
