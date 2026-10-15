"""Reads a pull request through the GitHub REST and GraphQL APIs."""

from collections.abc import Mapping
from functools import cached_property
from http import HTTPStatus
from typing import Self
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

from bylaw.diff import parse_patch
from bylaw.model import ChangedFile, FileStatus
from bylaw.source import ChangeInfo, Issue, IssueRef

_PAGE_SIZE = 100
_MAX_FILE_PAGES = 30  # GitHub lists at most 3000 files for a pull request.
_MAX_COMMIT_PAGES = 3  # and at most 250 commits.
_STATUS: dict[str, FileStatus] = {"added": "added", "removed": "removed", "renamed": "renamed"}
_CLOSING_QUERY = """
query($owner: String!, $name: String!, $number: Int!) {
  repository(owner: $owner, name: $name) {
    pullRequest(number: $number) {
      closingIssuesReferences(first: 25) { nodes { number repository { nameWithOwner } } }
    }
  }
}
"""

Params = Mapping[str, str | int]


class GitHubError(Exception):
    """A GitHub API call failed. The message never contains the token."""


class _Model(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")


class _Ref(_Model):
    sha: str


class PullRequest(_Model):
    title: str
    body: str | None = None
    base: _Ref
    head: _Ref


class PullFile(_Model):
    filename: str
    status: str
    previous_filename: str | None = None
    patch: str | None = None


class _CommitDetail(_Model):
    message: str


class _Commit(_Model):
    commit: _CommitDetail


class _IssueResponse(_Model):
    title: str
    body: str | None = None
    pull_request: dict[str, object] | None = None


class _GqlRepo(_Model):
    name_with_owner: str = Field(alias="nameWithOwner")


class _GqlIssue(_Model):
    number: int
    repository: _GqlRepo


class _GqlConnection(_Model):
    nodes: list[_GqlIssue]


class _GqlPull(_Model):
    closing: _GqlConnection = Field(alias="closingIssuesReferences")


class _GqlRepository(_Model):
    pull_request: _GqlPull | None = Field(default=None, alias="pullRequest")


class _GqlData(_Model):
    repository: _GqlRepository | None = None


class _GqlResponse(_Model):
    data: _GqlData | None = None
    errors: list[dict[str, object]] | None = None


_PULL_FILES = TypeAdapter(list[PullFile])
_COMMITS = TypeAdapter(list[_Commit])


class GitHubClient:
    def __init__(
        self, token: str, api_url: str = "https://api.github.com", graphql_url: str | None = None
    ) -> None:
        self._api_url = api_url.rstrip("/")
        self._graphql_url = graphql_url or f"{self._api_url}/graphql"
        self._http = httpx.Client(
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "bylaw",
            },
            timeout=30.0,
        )

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self._http.close()

    def pull(self, repo: str, number: int) -> PullRequest:
        return PullRequest.model_validate(self._get(f"/repos/{repo}/pulls/{number}").json())

    def pull_files(self, repo: str, number: int) -> list[PullFile]:
        files: list[PullFile] = []
        for page in range(1, _MAX_FILE_PAGES + 1):
            params = {"per_page": _PAGE_SIZE, "page": page}
            batch = _PULL_FILES.validate_python(
                self._get(f"/repos/{repo}/pulls/{number}/files", params).json()
            )
            files.extend(batch)
            if len(batch) < _PAGE_SIZE:
                break
        return files

    def pull_commit_messages(self, repo: str, number: int) -> list[str]:
        messages: list[str] = []
        for page in range(1, _MAX_COMMIT_PAGES + 1):
            params = {"per_page": _PAGE_SIZE, "page": page}
            batch = _COMMITS.validate_python(
                self._get(f"/repos/{repo}/pulls/{number}/commits", params).json()
            )
            messages.extend(item.commit.message for item in batch)
            if len(batch) < _PAGE_SIZE:
                break
        return messages

    def file_text(self, repo: str, path: str, ref: str) -> str | None:
        response = self._get_optional(
            f"/repos/{repo}/contents/{quote(path)}", {"ref": ref}, accept="application/vnd.github.raw+json"
        )
        return None if response is None else response.content.decode("utf-8", errors="replace")

    def issue(self, ref: IssueRef) -> Issue | None:
        response = self._get_optional(f"/repos/{ref.owner}/{ref.repo}/issues/{ref.number}")
        if response is None:
            return None
        data = _IssueResponse.model_validate(response.json())
        if data.pull_request is not None:
            return None
        return Issue(ref=ref, title=data.title, body=data.body or "")

    def closing_issue_refs(self, repo: str, number: int) -> tuple[IssueRef, ...]:
        owner, _, name = repo.partition("/")
        variables = {"owner": owner, "name": name, "number": number}
        response = self._send(
            "POST", self._graphql_url, json={"query": _CLOSING_QUERY, "variables": variables}
        )
        _raise_for_status(response)
        payload = _GqlResponse.model_validate(response.json())
        if payload.errors:
            raise GitHubError(
                f"GitHub GraphQL query for closing issues failed: {payload.errors[0].get('message')}"
            )
        repository = payload.data.repository if payload.data else None
        pull = repository.pull_request if repository else None
        if pull is None:
            return ()
        refs: list[IssueRef] = []
        for node in pull.closing.nodes:
            ref_owner, _, ref_name = node.repository.name_with_owner.lower().partition("/")
            refs.append(IssueRef(ref_owner, ref_name, node.number))
        return tuple(refs)

    def _get(self, path: str, params: Params | None = None) -> httpx.Response:
        response = self._send("GET", f"{self._api_url}{path}", params=params)
        _raise_for_status(response)
        return response

    def _get_optional(
        self, path: str, params: Params | None = None, accept: str | None = None
    ) -> httpx.Response | None:
        response = self._send("GET", f"{self._api_url}{path}", params=params, accept=accept)
        if response.status_code == HTTPStatus.NOT_FOUND:
            return None
        _raise_for_status(response)
        return response

    def _send(
        self,
        method: str,
        url: str,
        *,
        params: Params | None = None,
        accept: str | None = None,
        json: object = None,
    ) -> httpx.Response:
        headers = {"Accept": accept} if accept else None
        try:
            return self._http.request(method, url, params=params, headers=headers, json=json)
        except httpx.HTTPError as error:
            raise GitHubError(f"Could not reach GitHub at {url}: {type(error).__name__}") from error


def _raise_for_status(response: httpx.Response) -> None:
    if response.is_success:
        return
    try:
        body = response.json()
    except ValueError:
        body = None
    message = str(body.get("message", "")) if isinstance(body, dict) else ""
    if response.headers.get("x-ratelimit-remaining") == "0":
        reset = response.headers.get("x-ratelimit-reset", "unknown")
        message = f"rate limit exceeded, resets at Unix time {reset}"
    request = response.request
    raise GitHubError(
        f"GitHub returned {response.status_code} for {request.method} {request.url.path}: {message}"
    )


class GitHubSource:
    def __init__(self, client: GitHubClient, repo: str, number: int) -> None:
        self._client = client
        self._repo = repo.lower()
        self._number = number

    @property
    def repo(self) -> str:
        return self._repo

    @cached_property
    def _pull(self) -> PullRequest:
        return self._client.pull(self._repo, self._number)

    def info(self) -> ChangeInfo:
        pull = self._pull
        messages = tuple(self._client.pull_commit_messages(self._repo, self._number))
        return ChangeInfo(pull.base.sha, pull.head.sha, pull.title, pull.body or "", messages)

    def changed_files(self) -> tuple[ChangedFile, ...]:
        files: list[ChangedFile] = []
        for item in self._client.pull_files(self._repo, self._number):
            added, missing = parse_patch(item.patch) if item.patch is not None else ((), False)
            files.append(
                ChangedFile(
                    path=item.filename,
                    status=_STATUS.get(item.status, "modified"),
                    previous_path=item.previous_filename if item.status == "renamed" else None,
                    added_lines=added,
                    missing_final_newline=missing,
                    patch_omitted=item.patch is None,
                )
            )
        return tuple(files)

    def read_base(self, path: str) -> str | None:
        return self._client.file_text(self._repo, path, self._pull.base.sha)

    def read_head(self, path: str) -> str | None:
        return self._client.file_text(self._repo, path, self._pull.head.sha)

    def closing_issue_refs(self) -> tuple[IssueRef, ...]:
        return self._client.closing_issue_refs(self._repo, self._number)

    def read_issue(self, ref: IssueRef) -> Issue | None:
        return self._client.issue(ref)
