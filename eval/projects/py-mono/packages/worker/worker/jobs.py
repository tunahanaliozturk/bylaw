"""Queue jobs. The queue retries a job that raises and drops one that returns."""

import logging
import sqlite3

logger = logging.getLogger(__name__)


class JobError(Exception):
    """A job failed and should be retried."""


def send_receipt(connection: sqlite3.Connection, order_id: int) -> None:
    """Mark the order's receipt as sent."""
    updated = connection.execute("UPDATE orders SET receipt_sent = 1 WHERE id = ?", (order_id,)).rowcount
    if updated == 0:
        raise JobError(f"order {order_id} not found")
    logger.info("receipt sent for order %s", order_id)
