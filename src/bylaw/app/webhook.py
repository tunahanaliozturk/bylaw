"""Webhook deliveries: the signature check and the pull request events that start a review (ADR 0017)."""

import hashlib
import hmac
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from bylaw.app.queue import Job

# The actions the Action's workflow listens to as well; the others do not change what is reviewed.
REVIEW_ACTIONS = frozenset({"opened", "synchronize", "reopened", "ready_for_review"})

_Name = Annotated[str, Field(pattern=r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")]


class _Model(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore", hide_input_in_errors=True)


class _Installation(_Model):
    id: int = Field(gt=0)


class _Repository(_Model):
    full_name: _Name

    @field_validator("full_name")
    @classmethod
    def _no_dot_segments(cls, name: str) -> str:
        # The name goes into API paths; `..` there would point at another one.
        if any(part.strip(".") == "" for part in name.split("/")):
            raise ValueError("a part of the repository name is only dots")
        return name


class _Head(_Model):
    sha: str = Field(pattern=r"^[0-9a-f]{40}([0-9a-f]{24})?$")


class _Pull(_Model):
    head: _Head


class _Event(_Model):
    action: str
    number: int = Field(gt=0)
    installation: _Installation
    repository: _Repository
    pull_request: _Pull


def verify_signature(secret: bytes, body: bytes, signature: str | None) -> bool:
    """Whether `X-Hub-Signature-256` is the HMAC-SHA256 of the raw body under the webhook secret.

    The comparison takes the same time wherever the strings differ, so the signature cannot be guessed
    byte by byte from response times.
    """
    if not secret or not signature:
        return False
    expected = b"sha256=" + hmac.new(secret, body, hashlib.sha256).hexdigest().encode()
    # Bytes, not text: compare_digest raises on a string that is not ASCII, and the header is the sender's.
    return hmac.compare_digest(expected, signature.encode("utf-8", "surrogateescape"))


def review_job(event: str, body: bytes) -> Job | None:
    """The review a verified delivery asks for, None when it asks for none. Call only after the
    signature check: the body is parsed here."""
    if event != "pull_request":
        return None
    try:
        parsed = _Event.model_validate_json(body)
    except ValidationError:
        raise ValueError("not a pull_request event bylaw can read") from None
    if parsed.action not in REVIEW_ACTIONS:
        return None
    return Job(
        installation_id=parsed.installation.id,
        repo=parsed.repository.full_name,
        number=parsed.number,
        head_sha=parsed.pull_request.head.sha,
    )
