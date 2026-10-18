"""Reports built from the store's entries."""

import sqlite3
from contextlib import closing
from datetime import date

from ledger import store


def spent_between(start: date, end: date) -> int:
    """Total amount in cents from start to end, both included."""
    return sum(entry.amount_cents for entry in store.entries_between(start, end))


def largest_entries(limit: int) -> list[tuple[str, int]]:
    """The notes and amounts of the largest entries, largest first."""
    with closing(sqlite3.connect(store.DB_PATH)) as connection:
        rows = connection.execute(
            "SELECT note, amount_cents FROM entries ORDER BY amount_cents DESC LIMIT ?", (limit,)
        ).fetchall()
    return [(note, amount) for note, amount in rows]
