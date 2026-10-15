import sqlite3

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
