import sqlite3

import pytest

from app import accounts


def _db() -> sqlite3.Connection:
    db = sqlite3.connect(":memory:")
    db.execute("CREATE TABLE accounts (id INTEGER PRIMARY KEY, email TEXT UNIQUE, salt BLOB, password_hash BLOB)")
    return db


def test_the_right_password_signs_in() -> None:
    db = _db()
    created = accounts.sign_up(db, "shop@example.com", "correct horse")

    assert accounts.sign_in(db, "shop@example.com", "correct horse") == created


def test_a_wrong_password_does_not_sign_in() -> None:
    db = _db()
    accounts.sign_up(db, "shop@example.com", "correct horse")

    assert accounts.sign_in(db, "shop@example.com", "battery staple") is None


def test_a_failed_sign_in_is_logged_with_the_account_and_nothing_secret(caplog: pytest.LogCaptureFixture) -> None:
    db = _db()
    created = accounts.sign_up(db, "shop@example.com", "correct horse")

    accounts.sign_in(db, "shop@example.com", "battery staple")

    assert f"sign-in failed for account {created.id}" in caplog.text
    assert "battery staple" not in caplog.text
