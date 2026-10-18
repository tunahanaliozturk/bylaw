import sqlite3

from api import handlers


def _db() -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:")
    connection.execute("CREATE TABLE orders (id INTEGER PRIMARY KEY, status TEXT, total INTEGER)")
    connection.execute("INSERT INTO orders VALUES (1, 'paid', 1200)")
    return connection


def test_an_order_is_returned_by_id() -> None:
    result = handlers.get_order(_db(), 1)

    assert result.ok
    assert result.value == {"id": 1, "status": "paid", "total": 1200}


def test_a_missing_order_is_an_error_not_an_exception() -> None:
    result = handlers.get_order(_db(), 2)

    assert not result.ok
    assert result.error == "order 2 not found"
