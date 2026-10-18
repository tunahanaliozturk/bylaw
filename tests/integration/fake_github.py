"""A GitHub that answers the calls one bylaw review makes, in memory, for driving the app end to end.

It answers through respx, so no request leaves the machine. It is just enough GitHub for one repository
with one pull request, its organisation's `.github` repository and the app endpoints.
"""

import json
import re
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import unquote

import httpx

API = "https://api.github.test"
BASE_SHA = "b" * 40
HEAD_SHA = "a" * 40
OWNER = "acme"
REPO = "acme/app"
NUMBER = 5
SLUG = "bylaw-acme"


@dataclass
class Call:
    method: str
    path: str
    token: str
    body: Any


@dataclass
class FakeGitHub:
    base: dict[str, str] = field(default_factory=dict)
    org_defaults: str | None = None
    # Whether the installation covers the organisation's .github repository.
    org_installed: bool = True
    # The repository the token answer names, when it should differ from the one asked for.
    granted_repository: str | None = None
    comments: list[dict[str, Any]] = field(default_factory=list)
    reviews: list[dict[str, Any]] = field(default_factory=list)
    calls: list[Call] = field(default_factory=list)
    patch: str = "@@ -0,0 +1,2 @@\n+x = 1   \n+y = 2\n"
    title: str = "Add x"

    def __call__(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content else None
        path = unquote(request.url.path)
        token = request.headers.get("Authorization", "").removeprefix("Bearer ")
        self.calls.append(Call(request.method, path, token, body))
        return self._answer(request.method, path, request.url.params, body)

    def calls_to(self, method: str, prefix: str) -> list[Call]:
        return [c for c in self.calls if c.method == method and c.path.startswith(prefix)]

    def _answer(  # noqa: PLR0911, PLR0912 - one branch per endpoint
        self, method: str, path: str, params: httpx.QueryParams, body: Any
    ) -> httpx.Response:
        repo = f"/repos/{REPO}"
        if method == "GET" and path == "/app":
            return httpx.Response(200, json={"id": 1, "slug": SLUG})
        if method == "POST" and (match := re.fullmatch(r"/app/installations/(\d+)/access_tokens", path)):
            repositories = body["repositories"]
            if repositories == [".github"] and not self.org_installed:
                return httpx.Response(422, json={"message": "not accessible to the installation"})
            named = [{"full_name": self.granted_repository or f"{OWNER}/{name}"} for name in repositories]
            token = f"ghs_{match.group(1)}_{'_'.join(repositories)}"
            return httpx.Response(201, json={"token": token, "repositories": named})
        if method == "GET" and path == f"/repos/{OWNER}/.github/contents/.bylaw.toml":
            if self.org_defaults is None:
                return httpx.Response(404, json={"message": "Not Found"})
            return httpx.Response(200, content=self.org_defaults.encode())
        if method == "GET" and path == f"{repo}/pulls/{NUMBER}":
            return httpx.Response(200, json=self._pull())
        if method == "GET" and path == f"{repo}/pulls/{NUMBER}/commits":
            return httpx.Response(200, json=[{"commit": {"message": "Add x"}}])
        if method == "GET" and path == f"{repo}/pulls/{NUMBER}/files":
            file = {"filename": "app.py", "status": "added", "patch": self.patch, "changes": 2}
            return httpx.Response(200, json=[file] if params.get("page") == "1" else [])
        if method == "GET" and path == f"{repo}/git/trees/{BASE_SHA}":
            tree = [{"path": p, "type": "blob", "sha": f"sha-{p}"} for p in self.base]
            return httpx.Response(200, json={"tree": tree, "truncated": False})
        if method == "GET" and path.startswith(f"{repo}/contents/"):
            text = self.base.get(path.removeprefix(f"{repo}/contents/"))
            if text is None or params.get("ref") != BASE_SHA:
                return httpx.Response(404, json={"message": "Not Found"})
            return httpx.Response(200, content=text.encode())
        if path == f"{repo}/issues/{NUMBER}/comments":
            return self._comments(method, body, params)
        if method == "PATCH" and (match := re.fullmatch(rf"{repo}/issues/comments/(\d+)", path)):
            comment = next(c for c in self.comments if c["id"] == int(match.group(1)))
            comment["body"] = body["body"]
            return httpx.Response(200, json=comment)
        if method == "POST" and path == f"{repo}/pulls/{NUMBER}/reviews":
            self.reviews.append(body)
            return httpx.Response(200, json={"id": len(self.reviews)})
        if method == "POST" and path == "/graphql":
            return httpx.Response(200, json={"data": self._graphql(body["query"], body["variables"])})
        return httpx.Response(404, json={"message": f"the fake has no {method} {path}"})

    def _pull(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "body": "",
            "changed_files": 1,
            "user": {"type": "User", "login": "contributor"},
            "author_association": "CONTRIBUTOR",
            "base": {"sha": BASE_SHA},
            "head": {"sha": HEAD_SHA},
        }

    def _comments(self, method: str, body: Any, params: httpx.QueryParams) -> httpx.Response:
        if method == "POST":
            comment = {
                "id": 100 + len(self.comments),
                "body": body["body"],
                "user": {"type": "Bot", "login": f"{SLUG}[bot]"},
                "author_association": "NONE",
            }
            self.comments.append(comment)
            return httpx.Response(201, json=comment)
        return httpx.Response(200, json=self.comments if params.get("page") == "1" else [])

    def _graphql(self, query: str, variables: dict[str, Any]) -> dict[str, Any]:
        if "closingIssuesReferences" in query:
            return {"repository": {"pullRequest": {"closingIssuesReferences": {"nodes": []}}}}
        if "reviewThreads" in query:
            threads = {"pageInfo": {"hasNextPage": False, "endCursor": None}, "nodes": []}
            return {
                "repository": {"pullRequest": {"author": {"login": "contributor"}, "reviewThreads": threads}}
            }
        if "object(expression" in query:
            blobs: dict[str, Any] = {}
            for key, expression in variables.items():
                if re.fullmatch(r"e\d+", key):
                    ref, _, file = expression.partition(":")
                    text = self.base.get(file) if ref == BASE_SHA else None
                    blobs[f"f{key[1:]}"] = None if text is None else {"text": text, "isTruncated": False}
            return {"repository": blobs}
        return {}
