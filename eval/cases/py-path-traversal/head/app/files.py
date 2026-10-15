"""Uploaded avatars, kept under one directory."""

from pathlib import Path

UPLOAD_DIR = Path("uploads").resolve()


def save_avatar(user_id: int, data: bytes) -> Path:
    """Store an avatar under a name the server chooses, never one the client sends."""
    target = UPLOAD_DIR / f"{user_id}.png"
    target.write_bytes(data)
    return target


def read_avatar(user_id: int) -> bytes:
    """Return a stored avatar."""
    return (UPLOAD_DIR / f"{user_id}.png").read_bytes()


def read_upload(name: str) -> bytes:
    """Return an uploaded file by the name the client asks for."""
    return (UPLOAD_DIR / name).read_bytes()
