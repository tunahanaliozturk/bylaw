"""The only module that talks to the database (ADR 0002)."""

import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import date

DB_PATH = "ledger.db"


@dataclass(frozen=True)
class Entry:
    day: date
    amount_cents: int
    note: str


def connect(path: str = DB_PATH) -> sqlite3.Connection:
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    return connection


def add_entry(entry: Entry, path: str = DB_PATH) -> None:
    with closing(connect(path)) as connection, connection:
        connection.execute(
            "INSERT INTO entries (day, amount_cents, note) VALUES (?, ?, ?)",
            (entry.day.isoformat(), entry.amount_cents, entry.note),
        )


def entries_between(start: date, end: date, path: str = DB_PATH) -> list[Entry]:
    """Entries from start to end, both included, oldest first."""
    with closing(connect(path)) as connection:
        rows = connection.execute(
            "SELECT day, amount_cents, note FROM entries WHERE day BETWEEN ? AND ? ORDER BY day",
            (start.isoformat(), end.isoformat()),
        ).fetchall()
    return [Entry(date.fromisoformat(r["day"]), r["amount_cents"], r["note"]) for r in rows]
