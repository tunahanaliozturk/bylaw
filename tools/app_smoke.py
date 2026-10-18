"""End to end check of the GitHub App without GitHub: a real server process, a fake GitHub on a port.

    uv run python tools/app_smoke.py                  # the server as a local process
    uv run python tools/app_smoke.py --image bylaw-app  # the container image, which must be healthy

It starts the fake GitHub from tests/integration/fake_github.py on a local port, starts the app pointed at
it with a throwaway key and webhook secret, waits for the health endpoint (and, for an image, for Docker to
report the container healthy), posts one signed pull_request delivery and waits for the summary comment.
No model is called and nothing leaves the machine. Exit status 0 means the review ran end to end.
"""

import argparse
import hashlib
import hmac
import json
import os
import secrets
import socket
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Callable
from pathlib import Path

import httpx
import uvicorn
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import Response
from starlette.routing import Route

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tests.integration.fake_github import HEAD_SHA, NUMBER, REPO, FakeGitHub  # noqa: E402

TIMEOUT = 90.0


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def _fake_server(github: FakeGitHub, host: str, port: int) -> uvicorn.Server:
    async def answer(request: Request) -> Response:
        forwarded = httpx.Request(
            request.method, str(request.url), headers=request.headers.raw, content=await request.body()
        )
        reply = github(forwarded)
        return Response(reply.content, status_code=reply.status_code, headers=dict(reply.headers))

    app = Starlette(routes=[Route("/{path:path}", answer, methods=["GET", "POST", "PATCH"])])
    server = uvicorn.Server(uvicorn.Config(app, host=host, port=port, log_level="warning"))
    threading.Thread(target=server.run, daemon=True).start()
    while not server.started:
        time.sleep(0.05)
    return server


def _wait(what: str, ready: Callable[[], bool]) -> None:
    deadline = time.monotonic() + TIMEOUT
    while time.monotonic() < deadline:
        if ready():
            return
        time.sleep(0.5)
    raise SystemExit(f"app_smoke: timed out waiting for {what}")


def _healthy(url: str) -> bool:
    try:
        return httpx.get(url, timeout=2).status_code == 200  # noqa: PLR2004
    except httpx.HTTPError:
        return False


def _deliver(base: str, webhook_secret: str) -> tuple[httpx.Response, httpx.Response]:
    """One signed pull_request delivery, then the same body with a forged signature."""
    body = json.dumps(
        {
            "action": "opened",
            "number": NUMBER,
            "installation": {"id": 7},
            "repository": {"full_name": REPO},
            "pull_request": {"number": NUMBER, "head": {"sha": HEAD_SHA}},
        }
    ).encode()
    signature = "sha256=" + hmac.new(webhook_secret.encode(), body, hashlib.sha256).hexdigest()
    headers = {"X-GitHub-Event": "pull_request", "X-Hub-Signature-256": signature}
    answer = httpx.post(f"{base}/webhook", content=body, headers=headers, timeout=10)
    print(f"app_smoke: delivery answered {answer.status_code} {answer.text}")
    forged = httpx.post(
        f"{base}/webhook", content=body, headers={**headers, "X-Hub-Signature-256": "sha256=0"}
    )
    print(f"app_smoke: a forged delivery answered {forged.status_code}")
    return answer, forged


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--image", help="run this container image instead of a local process")
    args = parser.parse_args()

    work = Path(tempfile.mkdtemp(prefix="bylaw-app-smoke-"))
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    (work / "app.pem").write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
        )
    )
    webhook_secret = secrets.token_hex(32)
    (work / "webhook-secret").write_text(webhook_secret, encoding="utf-8")

    github = FakeGitHub(base={".editorconfig": "root = true\n[*]\ntrim_trailing_whitespace = true\n"})
    github.org_defaults = 'severity_threshold = "low"\n'
    fake_port, app_port = _free_port(), _free_port()
    # A container reaches the host through host.docker.internal, so the fake listens beyond loopback then.
    _fake_server(github, "0.0.0.0" if args.image else "127.0.0.1", fake_port)  # noqa: S104

    settings = {"BYLAW_APP_CLIENT_ID": "Iv23smoke", "PYTHONUNBUFFERED": "1"}
    if args.image:
        settings |= {
            "GITHUB_API_URL": f"http://host.docker.internal:{fake_port}",
            "BYLAW_APP_PRIVATE_KEY_FILE": "/run/secrets/app.pem",
            "BYLAW_WEBHOOK_SECRET_FILE": "/run/secrets/webhook-secret",
        }
        name = f"bylaw-app-smoke-{app_port}"
        command = ["docker", "run", "--rm", "--name", name, "-p", f"127.0.0.1:{app_port}:8000"]
        command += ["--add-host", "host.docker.internal:host-gateway", "-v", f"{work}:/run/secrets:ro"]
        for variable, value in settings.items():
            command += ["-e", f"{variable}={value}"]
        process = subprocess.Popen([*command, args.image])  # noqa: S603
    else:
        settings |= {
            "GITHUB_API_URL": f"http://127.0.0.1:{fake_port}",
            "BYLAW_APP_PRIVATE_KEY_FILE": str(work / "app.pem"),
            "BYLAW_WEBHOOK_SECRET_FILE": str(work / "webhook-secret"),
            "PORT": str(app_port),
        }
        launch = "from bylaw.app.server import main; main()"
        process = subprocess.Popen([sys.executable, "-c", launch], env={**os.environ, **settings})  # noqa: S603
    try:
        base = f"http://127.0.0.1:{app_port}"
        _wait("the health endpoint", lambda: _healthy(f"{base}/healthz"))
        print(f"app_smoke: {base}/healthz answers")
        if args.image:
            inspect = ["docker", "inspect", "--format", "{{.State.Health.Status}}", name]
            _wait(
                "Docker to report the container healthy",
                lambda: (
                    subprocess.run(inspect, capture_output=True, text=True, check=False).stdout.strip()  # noqa: S603
                    == "healthy"
                ),
            )
            print("app_smoke: Docker reports the container healthy")
        answer, forged = _deliver(base, webhook_secret)
        _wait("the summary comment", lambda: bool(github.comments) and bool(github.reviews))
        summary = github.comments[0]["body"]
        print(
            f"app_smoke: summary posted by {github.comments[0]['user']['login']}, {len(summary)} characters"
        )
        inline = [(c["path"], c["line"]) for c in github.reviews[0]["comments"]]
        print(f"app_smoke: inline comments {inline}")
        # The organisation's severity_threshold = "low" puts the trailing whitespace finding inline.
        ok = answer.status_code == 202 and forged.status_code == 401 and inline == [("app.py", 1)]  # noqa: PLR2004
        print("app_smoke: passed" if ok else "app_smoke: FAILED")
        return 0 if ok else 1
    finally:
        if args.image:
            subprocess.run(["docker", "stop", name], capture_output=True, check=False)  # noqa: S603, S607
        process.terminate()
        process.wait(timeout=30)


if __name__ == "__main__":
    raise SystemExit(main())
