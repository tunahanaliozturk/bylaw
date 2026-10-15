import sqlite3

import pytest

from app import users


def _db() -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, email TEXT UNIQUE, name TEXT)")
    return connection


def test_a_created_user_can_be_found_by_id() -> None:
    connection = _db()
    created = users.create(connection, "ada@example.com", "Ada")

    assert users.find_by_id(connection, created.id) == created


def test_pages_hold_size_users_and_start_at_one() -> None:
    connection = _db()
    for n in range(5):
        users.create(connection, f"u{n}@example.com", f"U{n}")

    assert [u.name for u in users.list_page(connection, 2, 2)] == ["U2", "U3"]


def test_rename_changes_the_display_name() -> None:
    connection = _db()
    user = users.create(connection, "ada@example.com", "Ada")

    users.rename(connection, user.id, "Ada L")

    assert users.find_by_id(connection, user.id) == users.User(user.id, "ada@example.com", "Ada L")


def test_a_name_over_50_characters_is_rejected() -> None:
    connection = _db()
    user = users.create(connection, "ada@example.com", "Ada")

    with pytest.raises(ValueError):
        users.rename(connection, user.id, "x" * 51)
