"""Reports built from the store's entries."""

from datetime import date

from ledger import store


def spent_between(start: date, end: date) -> int:
    """Total amount in cents from start to end, both included."""
    return sum(entry.amount_cents for entry in store.entries_between(start, end))
