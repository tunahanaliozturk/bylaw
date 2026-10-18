import hashlib
import hmac
import json

import pytest

from bylaw.app.queue import Job
from bylaw.app.webhook import review_job, verify_signature

SECRET = b"s3cret"
SHA = "a" * 40


def _sign(body: bytes, secret: bytes = SECRET) -> str:
    return "sha256=" + hmac.new(secret, body, hashlib.sha256).hexdigest()


def _event(action: str = "opened", **overrides: object) -> bytes:
    payload: dict[str, object] = {
        "action": action,
        "number": 5,
        "installation": {"id": 7},
        "repository": {"full_name": "acme/app"},
        "pull_request": {"number": 5, "head": {"sha": SHA}},
    }
    return json.dumps(payload | overrides).encode()


def test_a_body_signed_with_the_secret_is_accepted() -> None:
    body = _event()

    assert verify_signature(SECRET, body, _sign(body))


@pytest.mark.parametrize(
    "signature",
    [
        None,
        "",
        _sign(b"another body"),
        _sign(_event(), b"wrong secret"),
        # The SHA-1 header GitHub also sends is not accepted in place of the SHA-256 one.
        "sha1=" + hmac.new(SECRET, _event(), hashlib.sha1).hexdigest(),
        _sign(_event()).removeprefix("sha256="),
        _sign(_event()).upper(),
        # Not ASCII: compare_digest on such strings raises instead of answering no.
        "sha256=" + "é" * 64,
        "sha256=☃",
    ],
)
def test_a_missing_wrong_or_other_algorithm_signature_is_refused(signature: str | None) -> None:
    assert not verify_signature(SECRET, _event(), signature)


def test_an_empty_secret_refuses_everything() -> None:
    body = _event()

    assert not verify_signature(b"", body, _sign(body, b""))


@pytest.mark.parametrize("action", ["opened", "synchronize", "reopened", "ready_for_review"])
def test_the_four_review_actions_become_a_job(action: str) -> None:
    assert review_job("pull_request", _event(action)) == Job(
        installation_id=7, repo="acme/app", number=5, head_sha=SHA
    )


@pytest.mark.parametrize(
    ("event", "body"),
    [
        ("pull_request", _event("closed")),
        ("pull_request", _event("labeled")),
        ("issue_comment", _event()),
        ("installation", b'{"action": "created"}'),
    ],
)
def test_other_events_and_actions_are_nothing_to_do(event: str, body: bytes) -> None:
    assert review_job(event, body) is None


@pytest.mark.parametrize(
    "body",
    [
        b"not json",
        b"[]",
        _event(installation=None),
        _event(repository={"full_name": "../../etc"}),
        _event(repository={"full_name": "acme/app/../x"}),
        _event(repository={"full_name": "../x"}),
        _event(repository={"full_name": "acme/.."}),
        _event(pull_request={"number": 5, "head": {"sha": "HEAD; rm -rf /"}}),
        _event(number="5x"),
    ],
)
def test_a_malformed_pull_request_event_is_refused(body: bytes) -> None:
    with pytest.raises(ValueError, match="pull_request event"):
        review_job("pull_request", body)
