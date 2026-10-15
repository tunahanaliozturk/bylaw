"""Transactional email text."""

from app.users import User


def welcome_message(user: User) -> tuple[str, str]:
    """Subject and body for the email a new user receives."""
    return "Welcome", f"Hello {user.name}, your account is ready."
