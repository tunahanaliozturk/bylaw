import io
import sqlite3

from app import users
from app.export import export_csv


def test_each_user_becomes_one_csv_line() -> None:
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, email TEXT UNIQUE, name TEXT)")
    users.create(connection, "ada@example.com", "Ada")
    out = io.StringIO()

    assert export_csv(connection, out) == 1
    assert out.getvalue().splitlines() == ["1,ada@example.com,Ada"]
