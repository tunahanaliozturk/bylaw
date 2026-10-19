"""A GitHub that answers the calls one bylaw review makes, in memory, for driving the app end to end.

It answers through respx, so no request leaves the machine. It is just enough GitHub for one repository
with one pull request, its organisation's `.github` repository and the app endpoints, plus a small git
(branches, trees, commits) and pull request listing for learning (ADR 0022).
"""

import hashlib
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
_BASE_TREE = "t" * 40


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
    # A member's branch in the same repository unless a test says otherwise; None is a deleted fork.
    author_association: str = "MEMBER"
    head_repo: str | None = REPO
    labels: list[str] = field(default_factory=list)
    merged: bool = False
    closed_at: str | None = None
    # Review threads as GraphQL nodes; every inline comment a review posts opens one.
    threads: list[dict[str, Any]] = field(default_factory=list)
    # Git: branch name to commit, commit to its tree and parents, tree to its files. `main` is the base.
    branches: dict[str, str] = field(default_factory=lambda: {"main": BASE_SHA})
    commits: dict[str, dict[str, Any]] = field(default_factory=dict)
    trees: dict[str, dict[str, str]] = field(default_factory=dict)
    # Pull requests opened through the API.
    opened: list[dict[str, Any]] = field(default_factory=list)
    # How many branch updates another writer beats bylaw to, as two closing pull requests would.
    races: int = 0
    # Writes refused as a read-only GITHUB_TOKEN refuses them.
    read_only: bool = False
    # Pull requests refused, as when Actions may not create them.
    refuse_pulls: bool = False

    def __call__(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content else None
        path = unquote(request.url.path)
        token = request.headers.get("Authorization", "").removeprefix("Bearer ")
        self.calls.append(Call(request.method, path, token, body))
        return self._answer(request.method, path, request.url.params, body)

    def calls_to(self, method: str, prefix: str) -> list[Call]:
        return [c for c in self.calls if c.method == method and c.path.startswith(prefix)]

    def files(self, ref: str) -> dict[str, str] | None:
        """The files at a branch or a commit, None when there is no such thing."""
        sha = self.branches.get(ref, ref)
        if sha == BASE_SHA:
            return self.base
        commit = self.commits.get(sha)
        return None if commit is None else self.trees[commit["tree"]]

    def put_branch(self, name: str, files: dict[str, str]) -> None:
        """A branch with these files in one parentless commit, as an earlier run would have left it."""
        tree = _sha(files)
        self.trees[tree] = dict(files)
        commit = {"message": "earlier", "tree": tree, "parents": []}
        self.commits[_sha(commit)] = commit
        self.branches[name] = _sha(commit)

    def reply(self, thread: int, body: str, login: str, association: str = "MEMBER") -> None:
        node = {
            "body": body,
            "authorAssociation": association,
            "author": {"__typename": "User", "login": login},
        }
        self.threads[thread]["recent"]["nodes"].append(node)

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
        if path.startswith(f"{repo}/git/"):
            return self._git(method, path.removeprefix(f"{repo}/git/"), params, body)
        if method == "GET" and path.startswith(f"{repo}/contents/"):
            files = self.files(params.get("ref", "main"))
            text = None if files is None else files.get(path.removeprefix(f"{repo}/contents/"))
            if text is None:
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
            for comment in body["comments"]:
                self._open_thread(comment)
            return httpx.Response(200, json={"id": len(self.reviews)})
        if path == f"{repo}/pulls":
            return self._pulls(method, body, params)
        if method == "POST" and path == "/graphql":
            return httpx.Response(200, json={"data": self._graphql(body["query"], body["variables"])})
        return httpx.Response(404, json={"message": f"the fake has no {method} {path}"})

    def _pull(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "body": "",
            "changed_files": 1,
            "user": {"type": "User", "login": "contributor"},
            "author_association": self.author_association,
            "base": {"sha": BASE_SHA, "ref": "main", "repo": {"full_name": REPO}},
            "head": {
                "sha": HEAD_SHA,
                "repo": None if self.head_repo is None else {"full_name": self.head_repo},
            },
            "labels": [{"name": name} for name in self.labels],
            "merged": self.merged,
            "closed_at": self.closed_at,
        }

    def _open_thread(self, comment: dict[str, Any]) -> None:
        bylaw = {
            "body": comment["body"],
            "authorAssociation": "NONE",
            "author": {"__typename": "Bot", "login": SLUG},
        }
        self.threads.append(
            {
                "id": f"T{len(self.threads) + 1}",
                "isResolved": False,
                "resolvedBy": None,
                "path": comment["path"],
                "line": comment["line"],
                "comments": {"nodes": [bylaw]},
                "recent": {"nodes": [bylaw]},
            }
        )

    def _git(  # noqa: PLR0911, PLR0912 - one branch per endpoint
        self, method: str, path: str, params: httpx.QueryParams, body: Any
    ) -> httpx.Response:
        if method != "GET" and self.read_only:
            return httpx.Response(403, json={"message": "Resource not accessible by integration"})
        if method == "GET" and (match := re.fullmatch(r"ref/heads/(.+)", path)):
            sha = self.branches.get(match.group(1))
            if sha is None:
                return httpx.Response(404, json={"message": "Not Found"})
            return httpx.Response(200, json={"object": {"sha": sha}})
        if method == "GET" and (match := re.fullmatch(r"commits/(\w+)", path)):
            sha = match.group(1)
            tree = _BASE_TREE if sha == BASE_SHA else self.commits[sha]["tree"]
            return httpx.Response(200, json={"sha": sha, "tree": {"sha": tree}})
        if method == "GET" and (match := re.fullmatch(r"trees/(.+)", path)):
            files = self.files(match.group(1))
            if files is None:
                return httpx.Response(404, json={"message": "Not Found"})
            tree = [{"path": p, "type": "blob", "sha": f"sha-{p}"} for p in files]
            return httpx.Response(200, json={"tree": tree, "truncated": False})
        if method == "POST" and path == "trees":
            base = body.get("base_tree")
            files = dict(self.base if base == _BASE_TREE else self.trees[base] if base else {})
            files.update({entry["path"]: entry["content"] for entry in body["tree"]})
            sha = _sha(files)
            self.trees[sha] = files
            return httpx.Response(201, json={"sha": sha})
        if method == "POST" and path == "commits":
            sha = _sha(body)
            self.commits[sha] = body
            return httpx.Response(201, json={"sha": sha})
        if method == "POST" and path == "refs":
            name = body["ref"].removeprefix("refs/heads/")
            if name in self.branches:
                return httpx.Response(422, json={"message": "Reference already exists"})
            self.branches[name] = body["sha"]
            return httpx.Response(201, json={"ref": body["ref"]})
        if method == "PATCH" and (match := re.fullmatch(r"refs/heads/(.+)", path)):
            name = match.group(1)
            if self.races:
                self.races -= 1
                self._commit_as_someone_else(name)
            if self.commits[body["sha"]]["parents"] != [self.branches[name]]:
                return httpx.Response(422, json={"message": "Update is not a fast forward"})
            self.branches[name] = body["sha"]
            return httpx.Response(200, json={"object": {"sha": body["sha"]}})
        return httpx.Response(404, json={"message": f"the fake has no git {method} {path}"})

    def _commit_as_someone_else(self, branch: str) -> None:
        head = self.branches[branch]
        files = {**(self.files(head) or {}), f"pulls/{900 + self.races}.json": "{}"}
        tree = _sha(files)
        self.trees[tree] = files
        commit = {"message": "another pull request closed", "tree": tree, "parents": [head]}
        self.commits[_sha(commit)] = commit
        self.branches[branch] = _sha(commit)

    def _pulls(self, method: str, body: Any, params: httpx.QueryParams) -> httpx.Response:
        if method == "POST":
            if self.read_only or self.refuse_pulls:
                return httpx.Response(403, json={"message": "Resource not accessible by integration"})
            number = 100 + len(self.opened)
            self.opened.append({**body, "number": number})
            return httpx.Response(
                201, json={"number": number, "html_url": f"https://github.test/{REPO}/pull/{number}"}
            )
        head = params.get("head", "").partition(":")[2]
        return httpx.Response(200, json=[p for p in self.opened if p["head"] == head])

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
            threads = {"pageInfo": {"hasNextPage": False, "endCursor": None}, "nodes": self.threads}
            return {
                "repository": {"pullRequest": {"author": {"login": "contributor"}, "reviewThreads": threads}}
            }
        if "resolveReviewThread" in query or "unresolveReviewThread" in query:
            thread = next(t for t in self.threads if t["id"] == variables["id"])
            thread["isResolved"] = "unresolve" not in query
            return {"thread": {"id": thread["id"]}}
        if "object(expression" in query:
            blobs: dict[str, Any] = {}
            for key, expression in variables.items():
                if re.fullmatch(r"e\d+", key):
                    ref, _, file = expression.partition(":")
                    text = (self.files(ref) or {}).get(file)
                    blobs[f"f{key[1:]}"] = None if text is None else {"text": text, "isTruncated": False}
            return {"repository": blobs}
        return {}


def _sha(data: object) -> str:
    return hashlib.sha1(json.dumps(data, sort_keys=True).encode()).hexdigest()  # noqa: S324 - a fake's ids
