"""Fetch avatars from Gravatar."""

import hashlib

import requests


def gravatar(email: str) -> bytes:
    """Download the Gravatar image for an email address."""
    digest = hashlib.sha256(email.strip().lower().encode()).hexdigest()
    response = requests.get(f"https://www.gravatar.com/avatar/{digest}", timeout=5)
    response.raise_for_status()
    return response.content
