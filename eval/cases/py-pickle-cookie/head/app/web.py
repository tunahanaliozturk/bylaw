"""HTTP handlers. The framework adapter calls these with a parsed request."""

import base64
import pickle
from dataclasses import dataclass, field

from app import users
from app.db import connect


@dataclass(frozen=True)
class Request:
    path: str
    query: dict[str, str] = field(default_factory=dict)
    cookies: dict[str, str] = field(default_factory=dict)
    body: bytes = b""
    user_id: int | None = None


@dataclass(frozen=True)
class Response:
    status: int
    body: str = ""


def get_user(request: Request, user_id: int) -> Response:
    """Return a user's public profile."""
    with connect() as connection:
        user = users.find_by_id(connection, user_id)
    if user is None:
        return Response(404)
    return Response(200, user.name)


def preferences(request: Request) -> Response:
    """Return the theme saved in the preferences cookie."""
    saved = pickle.loads(base64.b64decode(request.cookies.get("prefs", "")))
    return Response(200, saved.get("theme", "light"))
