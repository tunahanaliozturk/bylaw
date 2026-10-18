"""How the app proves who it is: a JWT signed with its private key buys installation tokens (ADR 0017)."""

import time

import jwt

# What a review does with GitHub: read the change, the base branch and linked issues, then write review
# comments, the summary and thread resolutions, which pull request write covers. Contents stay read
# only, so a review token can never push code.
REVIEW_PERMISSIONS = {"contents": "read", "issues": "read", "metadata": "read", "pull_requests": "write"}
# For the organisation's `.github` repository, which only supplies default settings.
DEFAULTS_PERMISSIONS = {"contents": "read", "metadata": "read"}

_BACKDATE = 60  # seconds, against clock drift, as GitHub recommends
_LIFETIME = 540  # seconds after now; GitHub refuses a JWT that lives longer than ten minutes


def app_jwt(client_id: str, private_key: str, now: float | None = None) -> str:
    """A JWT that authenticates as the app itself. `client_id` may also be the numeric app id."""
    issued = int(time.time() if now is None else now)
    claims = {"iat": issued - _BACKDATE, "exp": issued + _LIFETIME, "iss": client_id}
    return jwt.encode(claims, private_key, algorithm="RS256")
