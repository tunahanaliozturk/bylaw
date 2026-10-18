"""The GitHub App end to end: signed deliveries into the ASGI app, a fake GitHub behind it, no network."""

import hashlib
import hmac
import json
import logging
from collections.abc import Iterator
from functools import cache
from pathlib import Path

import httpx2
import pytest
import respx
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from starlette.testclient import TestClient

from bylaw.app.auth import DEFAULTS_PERMISSIONS, REVIEW_PERMISSIONS
from bylaw.app.queue import ReviewQueue
from bylaw.app.secrets import EnvSecrets
from bylaw.app.server import MAX_BODY, Settings, SettingsError, create_app
from bylaw.engine import Reviewer
from bylaw.model import ReviewResult
from tests.integration.fake_github import API, HEAD_SHA, NUMBER, REPO, SLUG, FakeGitHub

SECRET = b"webhook-secret-for-tests"
EDITORCONFIG = "root = true\n[*]\ntrim_trailing_whitespace = true\n"


@cache
def _private_key() -> str:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    ).decode()


def _settings(environ: dict[str, str] | None = None) -> Settings:
    return Settings(
        client_id="Iv23test",
        private_key=_private_key(),
        webhook_secret=SECRET,
        secrets=EnvSecrets(environ or {}),
        api_url=API,
    )


def _event(action: str = "opened", sha: str = HEAD_SHA) -> bytes:
    return json.dumps(
        {
            "action": action,
            "number": NUMBER,
            "installation": {"id": 7},
            "repository": {"full_name": REPO},
            "pull_request": {"number": NUMBER, "head": {"sha": sha}},
        }
    ).encode()


def _sign(body: bytes) -> str:
    return "sha256=" + hmac.new(SECRET, body, hashlib.sha256).hexdigest()


def _deliver(
    client: TestClient, body: bytes, event: str = "pull_request", signature: str | None = None
) -> httpx2.Response:
    headers = {
        "X-GitHub-Event": event,
        "X-GitHub-Delivery": "72d3162e-cc78-11e3-81ab-4c9367dc0958",
        "X-Hub-Signature-256": _sign(body) if signature is None else signature,
        "Content-Type": "application/json",
    }
    return client.post("/webhook", content=body, headers=headers)


class FakeReviewer:
    def __init__(self) -> None:
        self.keys: list[str | None] = []

    def __call__(self, provider: str, model: str | None, effort: str | None, key: str | None) -> Reviewer:
        self.keys.append(key)
        return self

    def review(self, system: str, user: str) -> ReviewResult:
        return ReviewResult()


class Server:
    """The app under test with its fake GitHub; `settle` waits until every queued review is done."""

    def __init__(self, client: TestClient, queue: ReviewQueue, github: FakeGitHub, reviewer: FakeReviewer):
        self.client, self.queue, self.github, self.reviewer = client, queue, github, reviewer

    def deliver(
        self, body: bytes, event: str = "pull_request", signature: str | None = None
    ) -> httpx2.Response:
        return _deliver(self.client, body, event, signature)

    def settle(self) -> None:
        assert self.client.portal is not None
        self.client.portal.call(self.queue.join)


@pytest.fixture
def github() -> FakeGitHub:
    return FakeGitHub(base={".editorconfig": EDITORCONFIG})


def _serve(github: FakeGitHub, settings: Settings) -> Iterator[Server]:
    reviewer = FakeReviewer()
    app = create_app(settings, reviewer)
    with respx.mock(assert_all_called=False) as router:
        router.route(host="api.github.test").mock(side_effect=github)
        with TestClient(app) as client:
            yield Server(client, app.state.queue, github, reviewer)


@pytest.fixture
def server(github: FakeGitHub) -> Iterator[Server]:
    yield from _serve(github, _settings())


def test_a_signed_pull_request_event_is_answered_at_once_and_reviewed_in_the_background(
    server: Server,
) -> None:
    response = server.deliver(_event())
    server.settle()

    assert (response.status_code, response.json()) == (202, {"outcome": "queued"})
    [summary] = server.github.comments
    assert summary["body"].startswith("<!-- bylaw:summary -->")
    assert "Trailing whitespace" in summary["body"]


def test_the_review_runs_on_a_token_for_this_repository_with_the_narrowest_permissions(
    server: Server,
) -> None:
    server.deliver(_event())
    server.settle()

    tokens = server.github.calls_to("POST", "/app/installations/7/access_tokens")
    assert [c.body for c in tokens] == [
        {"repositories": ["app"], "permissions": REVIEW_PERMISSIONS},
        {"repositories": [".github"], "permissions": DEFAULTS_PERMISSIONS},
    ]
    repo_calls = [
        c for c in server.github.calls if c.path.startswith(f"/repos/{REPO}") or c.path == "/graphql"
    ]
    assert repo_calls
    assert {c.token for c in repo_calls} == {"ghs_7_app"}
    assert all(c.token.count(".") == 2 for c in tokens)  # a JWT buys the tokens


def test_a_redelivered_event_for_a_reviewed_head_does_nothing(server: Server) -> None:
    server.deliver(_event())
    server.settle()
    calls = len(server.github.calls)

    again = server.deliver(_event("synchronize"))
    server.settle()

    assert again.json() == {"outcome": "duplicate"}
    assert len(server.github.calls) == calls


def test_a_new_head_is_reviewed_again_and_updates_the_same_summary(server: Server) -> None:
    server.deliver(_event())
    server.settle()
    server.deliver(_event("synchronize", sha="c" * 40))
    server.settle()

    assert len(server.github.comments) == 1
    assert len(server.github.calls_to("PATCH", f"/repos/{REPO}/issues/comments/")) == 1


@pytest.mark.parametrize(
    "signature",
    ["", "sha256=" + "0" * 64, "sha1=0123", _sign(b"some other body")],
)
def test_a_delivery_without_a_valid_signature_is_refused_before_anything_runs(
    server: Server, signature: str
) -> None:
    calls = len(server.github.calls)

    response = server.deliver(_event(), signature=signature)
    server.settle()

    assert response.status_code == 401
    assert len(server.github.calls) == calls


def test_a_payload_over_the_limit_is_refused_unread(server: Server) -> None:
    body = b"{" + b" " * MAX_BODY + b"}"

    response = server.deliver(body)

    assert response.status_code == 413


def test_a_ping_other_events_and_other_actions_start_no_review(server: Server) -> None:
    calls = len(server.github.calls)

    answers = [
        server.deliver(b'{"zen": "Keep it logically awesome."}', event="ping"),
        server.deliver(b'{"action": "created"}', event="issue_comment"),
        server.deliver(_event("closed")),
    ]
    server.settle()

    assert [(a.status_code, a.json()) for a in answers] == [
        (200, {"ok": True}),
        (202, {"outcome": "ignored"}),
        (202, {"outcome": "ignored"}),
    ]
    assert len(server.github.calls) == calls


def test_a_signed_but_malformed_pull_request_event_is_a_bad_request(server: Server) -> None:
    response = server.deliver(b'{"action": "opened", "repository": {"full_name": "../x"}}')

    assert response.status_code == 400


def test_the_health_endpoint_answers_without_a_signature(server: Server) -> None:
    response = server.client.get("/healthz")

    assert (response.status_code, response.json()) == (200, {"status": "ok", "pending": 0, "running": 0})


def test_organisation_defaults_from_the_github_repository_apply(github: FakeGitHub) -> None:
    github.org_defaults = 'severity_threshold = "low"\n'
    for server in _serve(github, _settings()):
        server.deliver(_event())
        server.settle()

    [review] = github.reviews
    assert [(c["path"], c["line"]) for c in review["comments"]] == [("app.py", 1)]
    [read] = github.calls_to("GET", "/repos/acme/.github/contents/.bylaw.toml")
    assert read.token == "ghs_7_.github"  # noqa: S105 - the fake's token for that repository


def test_the_repository_s_base_branch_setting_overrides_the_organisation_default(github: FakeGitHub) -> None:
    github.org_defaults = 'severity_threshold = "low"\n'
    github.base[".bylaw.toml"] = 'severity_threshold = "medium"\n'
    for server in _serve(github, _settings()):
        server.deliver(_event())
        server.settle()

    assert github.reviews == []
    assert "Trailing whitespace" in github.comments[0]["body"]


def test_without_the_app_on_the_github_repository_the_review_goes_on_without_defaults(
    github: FakeGitHub,
) -> None:
    github.org_installed = False
    github.org_defaults = 'severity_threshold = "low"\n'
    for server in _serve(github, _settings()):
        server.deliver(_event())
        server.settle()

    assert github.reviews == []
    assert len(github.comments) == 1


def test_each_installation_reviews_with_its_own_model_key(github: FakeGitHub) -> None:
    environ = {"BYLAW_INSTALLATION_7_ANTHROPIC_API_KEY": "key-for-7", "ANTHROPIC_API_KEY": "not this"}
    for server in _serve(github, _settings(environ)):
        server.deliver(_event())
        server.settle()

        assert server.reviewer.keys == ["key-for-7"]


def test_an_installation_without_a_key_gets_the_deterministic_checks_only(server: Server) -> None:
    server.deliver(_event())
    server.settle()

    assert server.reviewer.keys == []
    assert "Trailing whitespace" in server.github.comments[0]["body"]


def test_a_summary_planted_by_another_bot_is_neither_trusted_nor_edited(github: FakeGitHub) -> None:
    planted = {
        "id": 1,
        "body": "<!-- bylaw:summary --> everything is fine",
        "user": {"type": "Bot", "login": "helpful-bot[bot]"},
        "author_association": "NONE",
    }
    github.comments.append(planted)
    for server in _serve(github, _settings()):
        server.deliver(_event())
        server.settle()

    assert github.calls_to("PATCH", f"/repos/{REPO}/issues/comments/") == []
    assert [c["user"]["login"] for c in github.comments] == ["helpful-bot[bot]", f"{SLUG}[bot]"]


def test_no_secret_reaches_the_log(github: FakeGitHub, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    environ = {"BYLAW_INSTALLATION_7_ANTHROPIC_API_KEY": "sk-ant-never-logged"}
    settings = _settings(environ)
    for server in _serve(github, settings):
        server.deliver(_event())
        server.settle()

    text = caplog.text + repr(settings)
    assert "#5" in caplog.text
    for secret in ("sk-ant-never-logged", SECRET.decode(), "ghs_7_app", "PRIVATE KEY"):
        assert secret not in text


def test_a_failed_review_is_logged_and_a_redelivery_retries_it(
    github: FakeGitHub, caplog: pytest.LogCaptureFixture
) -> None:
    github.base[".bylaw.toml"] = "max_comments = 500\n"
    for server in _serve(github, _settings()):
        server.deliver(_event())
        server.settle()
        retry = server.deliver(_event())
        server.settle()

    assert "ConfigError: .bylaw.toml on the base branch is invalid" in caplog.text
    assert retry.json() == {"outcome": "queued"}


def test_settings_come_from_the_environment_with_secrets_from_files(tmp_path: Path) -> None:
    key = tmp_path / "app.pem"
    key.write_text(_private_key(), encoding="utf-8")
    secret = tmp_path / "webhook"
    secret.write_text("from-a-file\n", encoding="utf-8")

    settings = Settings.from_env(
        {
            "BYLAW_APP_CLIENT_ID": "Iv23abc",
            "BYLAW_APP_PRIVATE_KEY_FILE": str(key),
            "BYLAW_WEBHOOK_SECRET_FILE": str(secret),
            "BYLAW_WEBHOOK_SECRET": "ignored when the file is set",
            "BYLAW_SECRETS_DIR": str(tmp_path),
            "BYLAW_APP_WORKERS": "4",
        }
    )

    assert (settings.client_id, settings.webhook_secret, settings.workers) == ("Iv23abc", b"from-a-file", 4)
    assert settings.private_key.startswith("-----BEGIN PRIVATE KEY-----")
    assert "DirectorySecrets" in repr(settings.secrets)


@pytest.mark.parametrize(
    ("environ", "message"),
    [
        ({}, "BYLAW_APP_CLIENT_ID is required"),
        ({"BYLAW_APP_CLIENT_ID": "x"}, "BYLAW_APP_PRIVATE_KEY_FILE or BYLAW_APP_PRIVATE_KEY is required"),
        (
            {"BYLAW_APP_CLIENT_ID": "x", "BYLAW_APP_PRIVATE_KEY": "k"},
            "BYLAW_WEBHOOK_SECRET_FILE or BYLAW_WEBHOOK_SECRET is required",
        ),
        (
            {"BYLAW_APP_CLIENT_ID": "x", "BYLAW_APP_PRIVATE_KEY_FILE": "/no/such/file"},
            "BYLAW_APP_PRIVATE_KEY_FILE cannot be read",
        ),
        (
            {
                "BYLAW_APP_CLIENT_ID": "x",
                "BYLAW_APP_PRIVATE_KEY": "k",
                "BYLAW_WEBHOOK_SECRET": "s",
                "BYLAW_PROVIDER": "x",
            },
            "BYLAW_PROVIDER must be one of",
        ),
    ],
)
def test_missing_or_wrong_settings_stop_the_server_with_the_variable_named(
    environ: dict[str, str], message: str
) -> None:
    with pytest.raises(SettingsError, match=message):
        Settings.from_env(environ)
