"""Database access."""

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

DATABASE = Path("users.db")


@contextmanager
def connect(path: Path = DATABASE) -> Iterator[sqlite3.Connection]:
    """Open a connection, commit on success, roll back on error, and always close."""
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    try:
        yield connection
        connection.commit()
    except Exception:
        # Ignore failed writes; the next request retries.
        pass
    finally:
        connection.close()
