"""Reads a GitLab merge request through the REST API v4 (ADR 0020).

Endpoints and fields are as documented at https://docs.gitlab.com/api/merge_requests/,
https://docs.gitlab.com/api/repository_files/ and https://docs.gitlab.com/api/repositories/.
"""

from collections.abc import Iterator, Mapping, Sequence
from functools import cached_property
from http import HTTPStatus
from typing import Self
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, TypeAdapter

from bylaw.diff import parse_patch
from bylaw.model import ChangedFile
from bylaw.source import ChangeInfo, SourceError

_PAGE_SIZE = 100
_MAX_PAGES = 50
# https://docs.gitlab.com/api/members/#roles: Developer and above can push code, the GitLab peer of
# GitHub's write access (ADR 0008).
DEVELOPER = 30

Params = Mapping[str, str | int]


class GitLabError(SourceError):
    """A GitLab API call failed. The message never contains the token."""


class _Model(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")


class _User(_Model):
    id: int
    username: str = ""


class _DiffRefs(_Model):
    base_sha: str
    start_sha: str
    head_sha: str


class _References(_Model):
    full: str = ""


class _MergeRequest(_Model):
    iid: int
    title: str
    description: str | None = None
    author: _User | None = None
    references: _References | None = None
    diff_refs: _DiffRefs | None = None


class _Diff(_Model):
    old_path: str
    new_path: str
    diff: str = ""
    new_file: bool = False
    renamed_file: bool = False
    deleted_file: bool = False
    too_large: bool = False
    collapsed: bool = False


class _Commit(_Model):
    message: str = ""


class _TreeEntry(_Model):
    type: str
    name: str
    path: str


class _Member(_Model):
    access_level: int = 0


_DIFFS = TypeAdapter(list[_Diff])
_COMMITS = TypeAdapter(list[_Commit])
_TREE = TypeAdapter(list[_TreeEntry])


class GitLabClient:
    """Thin HTTP over the REST API; the merge request logic lives in GitLabMergeRequest."""

    def __init__(self, token: str, api_url: str = "https://gitlab.com/api/v4") -> None:
        self.api_url = api_url.rstrip("/")
        # https://docs.gitlab.com/api/rest/authentication/: personal, project and group access tokens.
        self._http = httpx.Client(headers={"PRIVATE-TOKEN": token, "User-Agent": "bylaw"}, timeout=30.0)

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self._http.close()

    def get(self, path: str, params: Params | None = None) -> object:
        return self.send("GET", path, params=params).json()

    def get_optional(self, path: str, params: Params | None = None) -> httpx.Response | None:
        """None for a 404: a file or directory that is not there."""
        response = self._request("GET", f"{self.api_url}{path}", params=params)
        if response.status_code == HTTPStatus.NOT_FOUND:
            return None
        _raise_for_status(response)
        return response

    def pages(self, path: str, params: Params | None = None, *, missing_ok: bool = False) -> Iterator[object]:
        """Each page of a list, following the `Link: rel="next"` header GitLab sends for offset and
        keyset pagination alike (https://docs.gitlab.com/api/rest/#pagination). With `missing_ok`, a 404
        is an empty list."""
        url: str | None = f"{self.api_url}{path}"
        query: Params | None = {"per_page": _PAGE_SIZE, **(params or {})}
        for _ in range(_MAX_PAGES):
            if url is None:
                return
            response = self._request("GET", url, params=query)
            if missing_ok and response.status_code == HTTPStatus.NOT_FOUND:
                return
            _raise_for_status(response)
            yield response.json()
            url = response.links.get("next", {}).get("url")
            query = None  # the next link carries every parameter

    def send(
        self, method: str, path: str, *, params: Params | None = None, json: object = None
    ) -> httpx.Response:
        response = self._request(method, f"{self.api_url}{path}", params=params, json=json)
        _raise_for_status(response)
        return response

    def _request(
        self, method: str, url: str, *, params: Params | None = None, json: object = None
    ) -> httpx.Response:
        try:
            return self._http.request(method, url, params=params, json=json)
        except httpx.HTTPError as error:
            raise GitLabError(f"Could not reach GitLab at {url}: {type(error).__name__}") from error


def _raise_for_status(response: httpx.Response) -> None:
    if response.is_success:
        return
    try:
        body = response.json()
    except ValueError:
        body = None
    message = str(body.get("message", body.get("error", ""))) if isinstance(body, dict) else ""
    if response.status_code == HTTPStatus.TOO_MANY_REQUESTS:
        message = (
            f"rate limit exceeded, resets at Unix time {response.headers.get('ratelimit-reset', 'unknown')}"
        )
    request = response.request
    raise GitLabError(
        f"GitLab returned {response.status_code} for {request.method} {request.url.path}: {message}"
    )


def project_path(project: str) -> str:
    """The `:id` of a project, a number or a URL-encoded path (https://docs.gitlab.com/api/rest/#namespaced-paths)."""
    return quote(project, safe="")


class GitLabMergeRequest:
    """A merge request as a RepoSource."""

    def __init__(self, client: GitLabClient, project: str, iid: int) -> None:
        self._client = client
        self._project = project
        self._iid = iid
        self._levels: dict[tuple[str, int], int] = {}

    @property
    def _base(self) -> str:
        return f"/projects/{project_path(self._project)}"

    @property
    def _mr_path(self) -> str:
        return f"{self._base}/merge_requests/{self._iid}"

    @cached_property
    def _mr(self) -> _MergeRequest:
        return _MergeRequest.model_validate(self._client.get(self._mr_path))

    @property
    def _refs(self) -> _DiffRefs:
        if self._mr.diff_refs is None:
            # https://docs.gitlab.com/api/merge_requests/#empty-api-fields-for-new-merge-requests
            raise SourceError(
                f"GitLab has not finished computing the diff of merge request !{self._iid}; run bylaw again."
            )
        return self._mr.diff_refs

    @property
    def repo(self) -> str:
        """The project's full path, which issue references and `issue_repos` use."""
        full = self._mr.references.full if self._mr.references else ""
        return (full.rpartition("!")[0] or self._project).lower()

    def info(self) -> ChangeInfo:
        refs = self._refs
        messages: list[str] = []
        for page in self._client.pages(f"{self._mr_path}/commits"):
            messages.extend(c.message for c in _COMMITS.validate_python(page))
        author = self._mr.author
        return ChangeInfo(
            # The target branch commit, not the merge base: an old branch point must not bring old rules
            # with it (ADR 0004). GitHub's base sha is the target branch head too.
            refs.start_sha,
            refs.head_sha,
            self._mr.title,
            self._mr.description or "",
            tuple(messages),
            # ponytail: GitLab's changes_count is a string capped at "1000+"; no note about a cut listing
            # until a merge request that big needs one.
            None,
            author is not None and self.access_level(self._project, author.id) >= DEVELOPER,
        )

    def access_level(self, project: str, user_id: int) -> int:
        """The user's highest role in a project, inherited and invited ones included; 0 for a non-member
        (https://docs.gitlab.com/api/members/#retrieve-a-member-of-a-project)."""
        key = (project, user_id)
        if key not in self._levels:
            response = self._client.get_optional(f"/projects/{project_path(project)}/members/all/{user_id}")
            self._levels[key] = (
                0 if response is None else _Member.model_validate(response.json()).access_level
            )
        return self._levels[key]

    @cached_property
    def _files(self) -> tuple[ChangedFile, ...]:
        files: list[ChangedFile] = []
        for page in self._client.pages(f"{self._mr_path}/diffs"):
            files.extend(_changed(item) for item in _DIFFS.validate_python(page))
        return tuple(files)

    def changed_files(self) -> tuple[ChangedFile, ...]:
        return self._files

    def read_base(self, path: str) -> str | None:
        return self._file(path, self._refs.start_sha)

    def read_head(self, path: str) -> str | None:
        return self._file(path, self._refs.head_sha)

    def read_base_many(self, paths: Sequence[str]) -> dict[str, str | None]:
        # ponytail: one request per file; GitLab's GraphQL `repository.blobs` reads many at once if needed.
        return {path: self.read_base(path) for path in paths}

    def list_base(self, directory: str) -> frozenset[str]:
        return frozenset(entry.name for entry in self._tree(directory, recursive=False))

    def list_base_tree(self, directory: str) -> frozenset[str]:
        return frozenset(entry.path for entry in self._tree(directory, recursive=True))

    def _tree(self, directory: str, *, recursive: bool) -> list[_TreeEntry]:
        """Blobs under a directory of the base; empty when it does not exist. Symlinks are blobs too."""
        params: dict[str, str | int] = {"ref": self._refs.start_sha}
        if directory:
            params["path"] = directory
        if recursive:
            params["recursive"] = "true"
        entries: list[_TreeEntry] = []
        for page in self._client.pages(f"{self._base}/repository/tree", params, missing_ok=True):
            entries.extend(e for e in _TREE.validate_python(page) if e.type == "blob")
        return entries

    def _file(self, path: str, ref: str) -> str | None:
        response = self._client.get_optional(
            f"{self._base}/repository/files/{quote(path, safe='')}/raw", {"ref": ref}
        )
        return None if response is None else response.content.decode("utf-8", errors="replace")


def _changed(item: _Diff) -> ChangedFile:
    added, missing = parse_patch(item.diff)
    omitted = True
    changes: int | None = None
    if item.too_large or item.collapsed:
        # GitLab does not count the lines of a diff it leaves out; any positive count reads as "too large".
        changes = 1
    elif item.diff.startswith("Binary files "):
        changes = None
    elif not item.diff:
        changes = 0  # a pure move, a mode change or an empty file
    else:
        omitted = False
    status = (
        "added"
        if item.new_file
        else "removed"
        if item.deleted_file
        else "renamed"
        if item.renamed_file
        else "modified"
    )
    return ChangedFile(
        path=item.new_path,
        status=status,
        previous_path=item.old_path if item.renamed_file else None,
        added_lines=added,
        missing_final_newline=missing,
        patch_omitted=omitted,
        patch=item.diff,
        changes=changes,
    )
