"""The webhook server: verify, queue, answer at once; a worker reviews with an installation token (ADR 0017).

Run it with `bylaw-app`; the settings come from the environment, listed in docs/app/deploy.md.
"""

import asyncio
import logging
import os
from collections.abc import AsyncIterator, Callable, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from bylaw.app.auth import DEFAULTS_PERMISSIONS, REVIEW_PERMISSIONS, app_jwt
from bylaw.app.queue import Job, Outcome, ReviewQueue, flat
from bylaw.app.secrets import DirectorySecrets, EnvSecrets, SecretStore
from bylaw.app.webhook import review_job, verify_signature
from bylaw.engine import PROVIDERS, Reviewer, api_key_for, make_reviewer
from bylaw.github import GitHubClient, GitHubError
from bylaw.pull_review import review_pull_request

log = logging.getLogger("bylaw.app")

# Anyone can send bytes before the signature is checked, so the body is read only this far. GitHub
# documents no size for a pull_request delivery, only a 25 MB cap on any payload. A typical one is tens
# of kilobytes; the largest part is the pull request body, at most 65,536 characters, which is 256 KiB
# even at four UTF-8 bytes each. BYLAW_APP_MAX_BODY raises the limit if a delivery is ever refused.
MAX_BODY = 512 * 1024
# A body that has not arrived by then is refused, so a slow sender cannot hold a connection open.
BODY_SECONDS = 10.0
# Open connections at once; beyond that Uvicorn answers 503. Idle keep-alive connections close after
# five seconds. Both are for a server that only GitHub needs to reach.
MAX_CONNECTIONS = 64
KEEP_ALIVE_SECONDS = 5
# GitHub answers this when a token asks for a repository the installation does not cover.
_NOT_INSTALLED = frozenset({404, 422})

type ReviewerFactory = Callable[[str, str | None, str | None, str | None], Reviewer]


class SettingsError(Exception):
    """The server cannot start with these settings. The message names the variable, never its value."""


@dataclass(frozen=True, slots=True)
class Settings:
    client_id: str
    private_key: str = field(repr=False)
    webhook_secret: bytes = field(repr=False)
    secrets: SecretStore
    provider: str = "anthropic"
    model: str | None = None
    effort: str | None = None
    api_url: str = "https://api.github.com"
    graphql_url: str | None = None
    workers: int = 2
    max_pending: int = 100
    max_body: int = MAX_BODY

    @classmethod
    def from_env(cls, environ: Mapping[str, str]) -> "Settings":
        client_id = environ.get("BYLAW_APP_CLIENT_ID", "")
        if not client_id:
            raise SettingsError("BYLAW_APP_CLIENT_ID is required: the app's client ID or app ID")
        provider = environ.get("BYLAW_PROVIDER") or "anthropic"
        if provider not in PROVIDERS:
            raise SettingsError(f"BYLAW_PROVIDER must be one of {', '.join(PROVIDERS)}")
        secrets_dir = environ.get("BYLAW_SECRETS_DIR")
        api_url = environ.get("GITHUB_API_URL") or "https://api.github.com"
        return cls(
            client_id=client_id,
            private_key=_secret(environ, "BYLAW_APP_PRIVATE_KEY"),
            webhook_secret=_secret(environ, "BYLAW_WEBHOOK_SECRET").encode(),
            secrets=DirectorySecrets(Path(secrets_dir)) if secrets_dir else EnvSecrets(environ),
            provider=provider,
            model=environ.get("BYLAW_MODEL") or None,
            effort=environ.get("BYLAW_EFFORT") or None,
            api_url=api_url,
            graphql_url=environ.get("GITHUB_GRAPHQL_URL") or None,
            workers=_count(environ, "BYLAW_APP_WORKERS", 2),
            max_pending=_count(environ, "BYLAW_APP_MAX_PENDING", 100),
            max_body=_count(environ, "BYLAW_APP_MAX_BODY", MAX_BODY),
        )


def _secret(environ: Mapping[str, str], name: str) -> str:
    """`<name>_FILE`, a mounted file, wins over `<name>` itself, which ends up in `docker inspect`."""
    if path := environ.get(f"{name}_FILE"):
        try:
            value = Path(path).read_text(encoding="utf-8").strip()
        except OSError as error:
            raise SettingsError(f"{name}_FILE cannot be read: {type(error).__name__}") from None
    else:
        value = environ.get(name, "").strip()
    if not value:
        raise SettingsError(f"{name}_FILE or {name} is required")
    return value


def _count(environ: Mapping[str, str], name: str, default: int) -> int:
    raw = environ.get(name) or str(default)
    if not raw.isdigit() or int(raw) < 1:
        raise SettingsError(f"{name} must be a whole number of at least 1")
    return int(raw)


def create_app(settings: Settings, reviewer: ReviewerFactory = make_reviewer) -> Starlette:
    login: list[str] = []  # the app's bot login, read once at startup

    def run(job: Job) -> str:
        return review(settings, job, login[0], reviewer)

    queue = ReviewQueue(run, workers=settings.workers, max_pending=settings.max_pending)

    @asynccontextmanager
    async def lifespan(_: Starlette) -> AsyncIterator[None]:
        login.append(await asyncio.to_thread(_app_login, settings))
        log.info("bylaw app %s is listening for pull request events", login[0])
        async with queue.running():
            yield

    async def webhook(request: Request) -> Response:
        try:
            body = await read_body(request, settings.max_body)
        except RefusedError as refused:
            return JSONResponse({"error": refused.reason}, status_code=refused.status)
        # Nothing in the body is parsed before the signature says GitHub sent it.
        if not verify_signature(settings.webhook_secret, body, request.headers.get("X-Hub-Signature-256")):
            return JSONResponse({"error": "invalid signature"}, status_code=401)
        event = request.headers.get("X-GitHub-Event", "")
        if event == "ping":
            return JSONResponse({"ok": True})
        try:
            job = review_job(event, body)
        except ValueError as error:
            return JSONResponse({"error": str(error)}, status_code=400)
        if job is None:
            return JSONResponse({"outcome": "ignored"}, status_code=202)
        outcome = queue.offer(job)
        log.info("%s#%d at %s: %s", job.repo, job.number, job.head_sha[:12], outcome)
        status = 503 if outcome is Outcome.BUSY else 202
        return JSONResponse({"outcome": outcome}, status_code=status)

    async def health(_: Request) -> Response:
        return JSONResponse({"status": "ok", **queue.stats()})

    app = Starlette(
        routes=[Route("/webhook", webhook, methods=["POST"]), Route("/healthz", health, methods=["GET"])],
        lifespan=lifespan,
    )
    app.state.queue = queue
    return app


def review(settings: Settings, job: Job, bot_login: str, reviewer: ReviewerFactory = make_reviewer) -> str:
    """The same review as `bylaw review --pr N --post`, with a token for this one repository. Returns the
    head commit it read."""
    owner, _, name = job.repo.partition("/")
    with GitHubClient(app_jwt(settings.client_id, settings.private_key), settings.api_url) as app:
        token = _scoped_token(app, job.installation_id, owner, name, REVIEW_PERMISSIONS)
        defaults = _org_defaults(app, settings, job.installation_id, owner)
    secrets = settings.secrets.secrets(job.installation_id)
    key = api_key_for(settings.provider, secrets)
    make = None
    if key is not None:
        make = lambda: reviewer(settings.provider, settings.model, settings.effort, key)  # noqa: E731

    def say(text: str) -> None:
        log.info("%s#%d: %s", job.repo, job.number, flat(text))

    with GitHubClient(token, settings.api_url, settings.graphql_url, bot_login=bot_login) as client:
        done = review_pull_request(
            client, job.repo, job.number, make=make, post=True, say=say, defaults=defaults, env=secrets
        )
    return done.head_sha


def _org_defaults(app: GitHubClient, settings: Settings, installation_id: int, owner: str) -> str | None:
    """The `.bylaw.toml` on the default branch of the owner's `.github` repository, read with a token
    that can read nothing else; None when there is none or the app is not installed there."""
    try:
        token = _scoped_token(app, installation_id, owner, ".github", DEFAULTS_PERMISSIONS)
    except GitHubError as error:
        if error.status not in _NOT_INSTALLED:
            raise
        return None
    with GitHubClient(token, settings.api_url) as client:
        return client.file_text(f"{owner}/.github", ".bylaw.toml", None)


def _scoped_token(
    app: GitHubClient, installation_id: int, owner: str, name: str, permissions: Mapping[str, str]
) -> str:
    """A token for exactly `owner/name`. GitHub's answer must name that repository, so a mix-up between
    installations or a changed API never sends one repository's review through another's token."""
    granted = app.installation_token(installation_id, [name], permissions)
    expected = f"{owner}/{name}".lower()
    if granted.repositories != {expected}:
        raise GitHubError(f"the installation token GitHub returned is not for {expected}")
    return granted.token


def _app_login(settings: Settings) -> str:
    with GitHubClient(app_jwt(settings.client_id, settings.private_key), settings.api_url) as app:
        return app.app_login()


class RefusedError(Exception):
    """A delivery refused before it is read whole."""

    def __init__(self, status: int, reason: str) -> None:
        super().__init__(reason)
        self.status = status
        self.reason = reason


async def read_body(request: Request, limit: int = MAX_BODY, seconds: float = BODY_SECONDS) -> bytes:
    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > limit:
        raise RefusedError(413, "payload too large")
    chunks: list[bytes] = []
    size = 0
    try:
        async with asyncio.timeout(seconds):
            async for chunk in request.stream():
                size += len(chunk)
                if size > limit:
                    raise RefusedError(413, "payload too large")
                chunks.append(chunk)
    except TimeoutError:
        raise RefusedError(408, "the body took too long to arrive") from None
    return b"".join(chunks)


def main() -> None:
    import uvicorn  # noqa: PLC0415 - only the server needs it

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)  # one line per API call drowns the reviews
    try:
        settings = Settings.from_env(os.environ)
    except SettingsError as error:
        raise SystemExit(f"bylaw-app: {error}") from None
    host = os.environ.get("BYLAW_APP_HOST", "127.0.0.1")
    uvicorn.run(
        create_app(settings),
        host=host,
        port=_count(os.environ, "PORT", 8000),
        server_header=False,
        limit_concurrency=MAX_CONNECTIONS,
        timeout_keep_alive=KEEP_ALIVE_SECONDS,
    )
