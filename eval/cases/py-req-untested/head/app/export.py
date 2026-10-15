"""CSV export of all users."""

import csv
import sqlite3
from typing import TextIO


def export_csv(connection: sqlite3.Connection, out: TextIO) -> int:
    """Write every user as id, email, name in id order; return how many were written."""
    writer = csv.writer(out, lineterminator="\n")
    rows = connection.execute("SELECT id, email, name FROM users ORDER BY id").fetchall()
    for row in rows:
        writer.writerow([row["id"], row["email"], row["name"]])
    return len(rows)
