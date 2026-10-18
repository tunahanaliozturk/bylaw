"""Request handlers for the orders API."""

import sqlite3
from dataclasses import dataclass


@dataclass(frozen=True)
class Result:
    ok: bool
    value: object = None
    error: str = ""


def get_order(connection: sqlite3.Connection, order_id: int) -> Result:
    """Return the order with this id, or an error when there is none."""
    row = connection.execute("SELECT id, status, total FROM orders WHERE id = ?", (order_id,)).fetchone()
    if row is None:
        return Result(ok=False, error=f"order {order_id} not found")
    return Result(ok=True, value={"id": row[0], "status": row[1], "total": row[2]})
