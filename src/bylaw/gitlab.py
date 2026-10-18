"""Reads and comments on a GitLab merge request through the REST API v4 (ADR 0020).

Endpoints and fields are as documented at https://docs.gitlab.com/api/merge_requests/,
https://docs.gitlab.com/api/repository_files/, https://docs.gitlab.com/api/repositories/,
https://docs.gitlab.com/api/discussions/ and https://docs.gitlab.com/api/notes/.
"""

import hashlib
import re
from collections.abc import Iterator, Mapping, Sequence
from functools import cached_property
from http import HTTPStatus
from typing import Self
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, TypeAdapter

from bylaw.diff import parse_patch
from bylaw.github import ReviewComment, SummaryComment
from bylaw.model import ChangedFile
from bylaw.plan import Thread, ThreadComment
from bylaw.render import SUMMARY_MARKER
from bylaw.source import ChangeInfo, SourceError

_PAGE_SIZE = 100
_MAX_PAGES = 50
# https://docs.gitlab.com/api/members/#roles: Developer and above can push code, the GitLab peer of
# GitHub's write access (ADR 0008).
DEVELOPER = 30

Params = Mapping[str, str | int]


class GitLabError(SourceError):
    """A GitLab API call failed. The message never contains the token."""

    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


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


class _Position(_Model):
    new_path: str = ""
    new_line: int | None = None
    head_sha: str = ""


class _Note(_Model):
    id: int
    body: str = ""
    author: _User | None = None
    system: bool = False
    resolvable: bool = False
    resolved: bool = False
    position: _Position | None = None


class _Discussion(_Model):
    id: str
    individual_note: bool = False
    notes: list[_Note] = []


_DIFFS = TypeAdapter(list[_Diff])
_NOTES = TypeAdapter(list[_Note])
_DISCUSSIONS = TypeAdapter(list[_Discussion])
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
        f"GitLab returned {response.status_code} for {request.method} {request.url.path}: {message}",
        response.status_code,
    )


def project_path(project: str) -> str:
    """The `:id` of a project, a number or a URL-encoded path (https://docs.gitlab.com/api/rest/#namespaced-paths)."""
    return quote(project, safe="")


class GitLabMergeRequest:
    """A merge request as a RepoSource and as the Publisher that comments on it."""

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

    # Publishing (GLB-2). `repo` and `number` are part of the Publisher protocol; this object knows both.

    @cached_property
    def _own_id(self) -> int | None:
        """bylaw's own account: the token's user, such as a project access token's bot user. A token that
        cannot say who it is makes every summary someone else's, so its review memory is never trusted."""
        try:
            return _User.model_validate(self._client.get("/user")).id
        except GitLabError:
            return None

    def _trusted(self, user: _User | None) -> bool:
        """ADR 0008 on GitLab: bylaw's own account, or a Developer, Maintainer or Owner of the project."""
        if user is None:
            return False
        return user.id == self._own_id or self.access_level(self._project, user.id) >= DEVELOPER

    def review_threads(self, repo: str, number: int) -> list[Thread]:  # noqa: ARG002 - the Publisher protocol's arguments; this object knows them
        author = self._mr.author.id if self._mr.author else None
        head = self._refs.head_sha
        threads: list[Thread] = []
        for page in self._client.pages(f"{self._mr_path}/discussions"):
            for discussion in _DISCUSSIONS.validate_python(page):
                notes = [note for note in discussion.notes if not note.system]
                if discussion.individual_note or not notes:
                    continue
                position = notes[0].position
                resolvable = [note for note in notes if note.resolvable]
                comments = tuple(
                    ThreadComment(
                        body=note.body,
                        trusted=self._trusted(note.author),
                        by_pr_author=note.author is not None and note.author.id == author,
                    )
                    for note in notes
                )
                threads.append(
                    Thread(
                        id=discussion.id,
                        resolved=bool(resolvable) and all(note.resolved for note in resolvable),
                        comments=comments,
                        # A position GitLab could not carry to the newest diff stays on its old head.
                        line=position.new_line if position and position.head_sha == head else None,
                        original_line=position.new_line if position else None,
                        path=position.new_path if position else "",
                    )
                )
        return threads

    def summary_comment(self, repo: str, number: int) -> SummaryComment | None:  # noqa: ARG002 - the Publisher protocol's arguments; this object knows them
        """The note that opens with the summary marker, bylaw's own first (ADR 0008, ADR 0012)."""
        fallback: SummaryComment | None = None
        params = {"sort": "asc", "order_by": "created_at"}
        for page in self._client.pages(f"{self._mr_path}/notes", params):
            for note in _NOTES.validate_python(page):
                if note.system or not note.body.startswith(SUMMARY_MARKER) or not self._trusted(note.author):
                    continue
                if note.author is not None and note.author.id == self._own_id:
                    return SummaryComment(id=note.id, body=note.body, bot=True)
                fallback = fallback or SummaryComment(id=note.id, body=note.body)
        return fallback

    def upsert_summary(self, repo: str, number: int, comment_id: int | None, body: str) -> None:  # noqa: ARG002 - the Publisher protocol's arguments; this object knows them
        payload = {"body": _inert(body)}
        if comment_id is None:
            self._client.send("POST", f"{self._mr_path}/notes", json=payload)
        else:
            self._client.send("PUT", f"{self._mr_path}/notes/{comment_id}", json=payload)

    def create_review(
        self, repo: str, number: int, commit_id: str, body: str, comments: Sequence[ReviewComment]
    ) -> None:
        """One discussion per comment. GitLab has no review that groups them, so `body` is not posted, and
        the position uses the diff refs the change was read at, the commit `commit_id` names."""
        del repo, number, commit_id, body  # the Publisher protocol's arguments; this object knows them
        refs = self._refs
        files = {file.path: file for file in self._files}
        for comment in comments:
            file = files.get(comment.path)
            position: dict[str, object] = {
                "position_type": "text",
                "base_sha": refs.base_sha,
                "start_sha": refs.start_sha,
                "head_sha": refs.head_sha,
                "old_path": file.previous_path if file and file.previous_path else comment.path,
                "new_path": comment.path,
                "new_line": comment.line,
            }
            text = _note_body(comment.body, comment.line - comment.start_line)
            if (span := _line_range(file, comment)) is not None:
                try:
                    self._post_discussion(text, {**position, "line_range": span})
                    continue
                except GitLabError as error:
                    # The line codes are computed, not read; a range GitLab rejects still gets its comment.
                    if error.status != HTTPStatus.BAD_REQUEST:
                        raise
            self._post_discussion(text, position)

    def _post_discussion(self, body: str, position: dict[str, object]) -> None:
        self._client.send("POST", f"{self._mr_path}/discussions", json={"body": body, "position": position})

    def set_thread_resolved(self, thread_id: str, *, resolved: bool) -> None:
        path = f"{self._mr_path}/discussions/{quote(thread_id, safe='')}"
        self._client.send("PUT", path, params={"resolved": "true" if resolved else "false"})


def _line_range(file: ChangedFile | None, comment: ReviewComment) -> dict[str, object] | None:
    """A multi-line position. A line code is `<sha1 of the path>_<old>_<new>`, and an added line keeps the
    old file's line counter where it was inserted, as GitLab's diff parser numbers it."""
    if file is None or comment.start_line >= comment.line:
        return None
    old = _old_counters(file.patch)
    if comment.start_line not in old or comment.line not in old:
        return None
    sha = hashlib.sha1(comment.path.encode("utf-8")).hexdigest()  # noqa: S324 - GitLab's format, not a secret

    def end(line: int) -> dict[str, object]:
        return {"line_code": f"{sha}_{old[line]}_{line}", "type": "new", "new_line": line}

    return {"start": end(comment.start_line), "end": end(comment.line)}


_HUNK = re.compile(r"^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@")


def _old_counters(patch: str) -> dict[int, int]:
    """For each added line's number in the new file, the old file's line counter at that point."""
    counters: dict[int, int] = {}
    old = new = 0
    for line in patch.split("\n"):
        if hunk := _HUNK.match(line):
            old, new = int(hunk[1]), int(hunk[2])
        elif line.startswith("+"):
            counters[new] = old
            new += 1
        elif line.startswith("-"):
            old += 1
        elif not line.startswith("\\"):
            old += 1
            new += 1
    return counters


# The end of a body render.inline_body wrote: a suggestion's closing fence, "Also at", the fingerprint.
_SUGGESTION_END = re.compile(r"\n(`{3,})\n\n(?:Also at [^\n]*\n\n)?<!-- bylaw:fp=[0-9a-f]{16} -->\Z")


def _note_body(body: str, lines_above: int) -> str:
    """An inline comment for GitLab. A suggestion must cover every line of the comment, which GitLab writes
    `suggestion:-N+0` (https://docs.gitlab.com/user/project/merge_requests/reviews/suggestions/); every
    other line is made inert."""
    tail = _SUGGESTION_END.search(body)
    if tail is None:
        return _inert(body)
    fence = tail[1]
    # The suggestion holds no backtick run as long as its fence, so the last opener with it is bylaw's.
    openers = list(re.finditer(rf"(?m)^{fence}suggestion$", body[: tail.start()]))
    if not openers:
        return _inert(body)
    opener, close = openers[-1], tail.start() + 1 + len(fence)
    offset = f":-{lines_above}+0" if lines_above > 0 else ""
    return (
        _inert(body[: opener.start()])
        + body[opener.start() : opener.end()]
        + offset
        + body[opener.end() : close]
        + _inert(body[close:])
    )


def _inert(text: str) -> str:
    """GitLab runs a quick action (`/merge`, `/approve`, `/close`) from a note line that starts with a slash,
    as the token's user (https://docs.gitlab.com/user/project/quick_actions/). Text from a model or a merge
    request reaches these lines, so a zero-width space goes in front of every one. Lines in a code block
    need none, but telling a code block apart exactly as GitLab's Markdown does is where a mistake would
    hide, so only bylaw's own suggestion is left as written; GitLab reads no quick action inside it."""
    return "\n".join(f"&#8203;{line}" if line.startswith("/") else line for line in text.split("\n"))


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
