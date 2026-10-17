"""Reads a pull request through the GitHub REST and GraphQL APIs."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from functools import cached_property
from http import HTTPStatus
from typing import Self
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

from bylaw.diff import parse_patch
from bylaw.model import ChangedFile, FileStatus
from bylaw.plan import Thread, ThreadComment
from bylaw.render import SUMMARY_MARKER
from bylaw.source import ChangeInfo, Issue, IssueRef

_PAGE_SIZE = 100
_MAX_FILE_PAGES = 30  # GitHub lists at most 3000 files for a pull request.
_MAX_COMMIT_PAGES = 3  # and at most 250 commits.
_UNREADABLE_ISSUE = frozenset(
    {HTTPStatus.MOVED_PERMANENTLY, HTTPStatus.FORBIDDEN, HTTPStatus.NOT_FOUND, HTTPStatus.GONE}
)
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


class _GraphQLError(GitHubError):
    """GitHub answered a GraphQL query with errors in the body."""

    def __init__(self, errors: list[dict[str, object]]) -> None:
        super().__init__(f"GitHub GraphQL call failed: {errors[0].get('message')}")
        self.rate_limited = any(error.get("type") == "RATE_LIMITED" for error in errors)


class _Model(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")


class _Ref(_Model):
    sha: str


class PullRequest(_Model):
    title: str
    body: str | None = None
    changed_files: int | None = None
    user: "_User | None" = None
    base: _Ref
    head: _Ref


class PullFile(_Model):
    filename: str
    status: str
    previous_filename: str | None = None
    patch: str | None = None
    changes: int = 0
    sha: str | None = None


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


_ISSUE_COMMENTS_QUERY = """
query($owner: String!, $name: String!, $number: Int!, $before: String) {
  repository(owner: $owner, name: $name) {
    issue(number: $number) {
      comments(last: 100, before: $before) {
        pageInfo { hasPreviousPage startCursor }
        nodes { body isMinimized authorAssociation author { __typename login } }
      }
    }
  }
}
"""


class _GqlIssueComment(_Model):
    body: str = ""
    is_minimized: bool = Field(default=False, alias="isMinimized")
    author_association: str = Field(default="NONE", alias="authorAssociation")
    author: "_GqlAuthor | None" = None


class _GqlIssueComments(_Model):
    nodes: list[_GqlIssueComment]
    page_info: "_GqlCommentPage | None" = Field(default=None, alias="pageInfo")


class _GqlIssueWithComments(_Model):
    comments: _GqlIssueComments


class _GqlIssueRepository(_Model):
    issue: _GqlIssueWithComments | None = None


class _GqlIssueCommentsData(_Model):
    repository: _GqlIssueRepository | None = None


class _GqlIssueCommentsResponse(_Model):
    data: _GqlIssueCommentsData | None = None
    errors: list[dict[str, object]] | None = None


_PULL_FILES = TypeAdapter(list[PullFile])
_COMMITS = TypeAdapter(list[_Commit])

TRUSTED_ASSOCIATIONS = frozenset({"OWNER", "MEMBER", "COLLABORATOR"})
_THREADS_QUERY = """
query($owner: String!, $name: String!, $number: Int!, $after: String) {
  repository(owner: $owner, name: $name) {
    pullRequest(number: $number) {
      author { login }
      reviewThreads(first: 100, after: $after) {
        pageInfo { hasNextPage endCursor }
        nodes {
          id
          isResolved
          line
          originalLine
          comments: comments(first: 1) { nodes { id body authorAssociation author { __typename login } } }
          recent: comments(last: 100) {
            pageInfo { hasPreviousPage startCursor }
            nodes { id body authorAssociation author { __typename login } }
          }
        }
      }
    }
  }
}
"""
_RESOLVE = "mutation($id: ID!) { resolveReviewThread(input: {threadId: $id}) { thread { id } } }"
_UNRESOLVE = "mutation($id: ID!) { unresolveReviewThread(input: {threadId: $id}) { thread { id } } }"


class _GqlAuthor(_Model):
    typename: str = Field(default="", alias="__typename")
    login: str = ""


class _GqlComment(_Model):
    id: str = ""
    body: str
    author_association: str = Field(alias="authorAssociation")
    author: _GqlAuthor | None = None


class _GqlCommentPage(_Model):
    has_previous_page: bool = Field(default=False, alias="hasPreviousPage")
    start_cursor: str | None = Field(default=None, alias="startCursor")


class _GqlComments(_Model):
    nodes: list[_GqlComment]
    page_info: _GqlCommentPage | None = Field(default=None, alias="pageInfo")


class _GqlOlderNode(_Model):
    comments: _GqlComments


class _GqlOlderData(_Model):
    node: _GqlOlderNode | None = None


_OLDER_COMMENTS_QUERY = """
query($id: ID!, $before: String) {
  node(id: $id) {
    ... on PullRequestReviewThread {
      comments(last: 100, before: $before) {
        pageInfo { hasPreviousPage startCursor }
        nodes { id body authorAssociation author { __typename login } }
      }
    }
  }
}
"""
_MAX_THREAD_PAGES = 10


class _GqlThread(_Model):
    id: str
    is_resolved: bool = Field(alias="isResolved")
    line: int | None = None
    original_line: int | None = Field(default=None, alias="originalLine")
    # The finding itself and the newest replies: a mute or resolve is usually late in a long thread.
    comments: _GqlComments
    recent: _GqlComments = Field(default_factory=lambda: _GqlComments(nodes=[]))


class _GqlPageInfo(_Model):
    has_next_page: bool = Field(alias="hasNextPage")
    end_cursor: str | None = Field(default=None, alias="endCursor")


class _GqlThreads(_Model):
    page_info: _GqlPageInfo = Field(alias="pageInfo")
    nodes: list[_GqlThread]


class _GqlThreadPull(_Model):
    author: _GqlAuthor | None = None
    review_threads: _GqlThreads = Field(alias="reviewThreads")


class _GqlThreadRepository(_Model):
    pull_request: _GqlThreadPull | None = Field(default=None, alias="pullRequest")


class _GqlThreadData(_Model):
    repository: _GqlThreadRepository | None = None


class _User(_Model):
    kind: str = Field(default="User", alias="type")
    login: str = ""


class _IssueComment(_Model):
    id: int
    body: str = ""
    user: _User | None = None
    author_association: str = "NONE"


_ISSUE_COMMENTS = TypeAdapter(list[_IssueComment])


@dataclass(frozen=True, slots=True)
class SummaryComment:
    id: int
    body: str
    # Written by a bot account. Only then does its review memory decide what is reviewed again (ADR 0012).
    bot: bool = False


@dataclass(frozen=True, slots=True)
class ReviewComment:
    path: str
    line: int
    start_line: int
    body: str

    def payload(self) -> dict[str, object]:
        data: dict[str, object] = {"path": self.path, "line": self.line, "side": "RIGHT", "body": self.body}
        if self.start_line < self.line:
            data |= {"start_line": self.start_line, "start_side": "RIGHT"}
        return data


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

    def tree_shas(self, repo: str, sha: str) -> dict[str, str] | None:
        """Every blob's id at a commit in one call; None when GitHub truncated the listing."""
        body = self._get(f"/repos/{repo}/git/trees/{sha}", {"recursive": "1"}).json()
        if not isinstance(body, dict) or body.get("truncated"):
            return None
        entries = body.get("tree")
        if not isinstance(entries, list):
            return None
        return {
            e["path"]: e["sha"]
            for e in entries
            if isinstance(e, dict) and e.get("type") == "blob" and isinstance(e.get("path"), str)
        }

    def blob_sha(self, repo: str, path: str, ref: str) -> str | None:
        response = self._get_optional(f"/repos/{repo}/contents/{quote(path)}", {"ref": ref})
        sha = response.json().get("sha") if response is not None else None
        return sha if isinstance(sha, str) else None

    def issue(self, ref: IssueRef, exclude: str | None = None) -> Issue | None:
        """The issue with its trusted comments; `exclude` names the pull request author, never trusted."""
        response = self._send("GET", f"{self._api_url}/repos/{ref.owner}/{ref.repo}/issues/{ref.number}")
        # A moved, hidden, deleted or disabled issue leaves the review to go on without it; a rate limit
        # does not, because every later call would fail too.
        rate_limited = response.headers.get("x-ratelimit-remaining") == "0"
        if response.status_code in _UNREADABLE_ISSUE and not rate_limited:
            return None
        _raise_for_status(response)
        data = _IssueResponse.model_validate(response.json())
        if data.pull_request is not None:
            return None
        comments, unreadable = self._issue_comments(ref, exclude)
        # Bots post status, not requirements, and nobody outside the project may rescope the issue. The pull
        # request author is left out only as a member: an owner or collaborator could edit the issue body
        # anyway, but a member may have read access only (ADR 0008).
        trusted = [c.body for c in comments if c.body and _counts(c, exclude)]
        return Issue(
            ref=ref,
            title=data.title,
            body=data.body or "",
            comments=_newest_within(trusted),
            comments_unreadable=unreadable,
        )

    def _issue_comments(self, ref: IssueRef, exclude: str | None) -> tuple[list[_GqlIssueComment], bool]:
        """Comments from the newest back, oldest first, and whether they could not be read at all.

        GraphQL rather than REST: it pages from the newest comment and says which ones a maintainer hid.
        Paging stops once enough trusted comments are in hand, so a flood of outside comments on a popular
        issue cannot push a maintainer's earlier word out of reach.
        """
        comments: list[_GqlIssueComment] = []
        before: str | None = None
        for _ in range(_MAX_COMMENT_PAGES):
            variables = {"owner": ref.owner, "name": ref.repo, "number": ref.number, "before": before}
            response = self._send(
                "POST", self._graphql_url, json={"query": _ISSUE_COMMENTS_QUERY, "variables": variables}
            )
            if (
                response.status_code in _UNREADABLE_ISSUE
                and response.headers.get("x-ratelimit-remaining") != "0"
            ):
                return comments, not comments
            _raise_for_status(response)
            payload = _GqlIssueCommentsResponse.model_validate(response.json())
            if any(error.get("type") == "RATE_LIMITED" for error in payload.errors or []):
                raise GitHubError(
                    f"GitHub GraphQL rate limit reached while reading the comments on {ref.label(None)}"
                )
            repository = payload.data.repository if payload.data else None
            if repository is None or repository.issue is None:
                # Moved, deleted or hidden since the issue itself was read: go on without its comments.
                return comments, not comments
            page = repository.issue.comments
            comments = [*page.nodes, *comments]
            trusted = sum(1 for c in comments if c.body and _counts(c, exclude))
            if (
                trusted >= _MAX_ISSUE_COMMENTS
                or page.page_info is None
                or not page.page_info.has_previous_page
            ):
                break
            before = page.page_info.start_cursor
        return comments, False

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

    def review_threads(self, repo: str, number: int) -> list[Thread]:
        owner, _, name = repo.partition("/")
        threads: list[Thread] = []
        after: str | None = None
        while True:
            variables = {"owner": owner, "name": name, "number": number, "after": after}
            data = _GqlThreadData.model_validate(self._graphql(_THREADS_QUERY, variables))
            pull = data.repository.pull_request if data.repository else None
            if pull is None:
                return threads
            pr_author = pull.author.login if pull.author else None
            for node in pull.review_threads.nodes:
                read, unread = self._thread_comments(node)
                comments = tuple(
                    ThreadComment(
                        body=c.body,
                        trusted=_trusted(c.author.typename if c.author else "", c.author_association),
                        by_pr_author=c.author is not None and c.author.login == pr_author,
                    )
                    for c in read
                )
                threads.append(
                    Thread(
                        id=node.id,
                        resolved=node.is_resolved,
                        comments=comments,
                        line=node.line,
                        original_line=node.original_line,
                        older_replies_unread=unread,
                    )
                )
            if not pull.review_threads.page_info.has_next_page:
                return threads
            after = pull.review_threads.page_info.end_cursor

    def _thread_comments(self, thread: _GqlThread) -> tuple[list[_GqlComment], bool]:
        """The finding and every reply, and whether the older replies could not be read.

        A thread longer than the newest hundred is paged back to its start.
        """
        older: list[_GqlComment] = []
        unread = False
        page = thread.recent.page_info
        for _ in range(_MAX_THREAD_PAGES):
            if page is None or not page.has_previous_page:
                break
            try:
                raw = self._graphql(_OLDER_COMMENTS_QUERY, {"id": thread.id, "before": page.start_cursor})
            except _GraphQLError as error:
                if error.rate_limited:
                    raise
                # One thread's history should not end the run: the finding and the newest replies still count.
                unread = True
                break
            data = _GqlOlderData.model_validate(raw)
            if data.node is None:
                break
            older = [*data.node.comments.nodes, *older]
            page = data.node.comments.page_info
        merged = thread.model_copy(update={"recent": _GqlComments(nodes=[*older, *thread.recent.nodes])})
        return _first_and_recent(merged), unread

    def summary_comment(self, repo: str, number: int) -> SummaryComment | None:
        """The comment that opens with the summary marker, a bot's first (ADR 0008).

        A marker in the middle of a comment is someone quoting it; editing that comment would overwrite
        a person's words.
        """
        fallback: SummaryComment | None = None
        for page in range(1, _MAX_FILE_PAGES + 1):
            params = {"per_page": _PAGE_SIZE, "page": page}
            batch = _ISSUE_COMMENTS.validate_python(
                self._get(f"/repos/{repo}/issues/{number}/comments", params).json()
            )
            for comment in batch:
                kind = comment.user.kind if comment.user else ""
                if not comment.body.startswith(SUMMARY_MARKER) or not _trusted(
                    kind, comment.author_association
                ):
                    continue
                if kind == "Bot":
                    return SummaryComment(id=comment.id, body=comment.body, bot=True)
                fallback = fallback or SummaryComment(id=comment.id, body=comment.body)
            if len(batch) < _PAGE_SIZE:
                break
        return fallback

    def upsert_summary(self, repo: str, number: int, comment_id: int | None, body: str) -> None:
        if comment_id is None:
            url = f"{self._api_url}/repos/{repo}/issues/{number}/comments"
            _raise_for_status(self._send("POST", url, json={"body": body}))
        else:
            url = f"{self._api_url}/repos/{repo}/issues/comments/{comment_id}"
            _raise_for_status(self._send("PATCH", url, json={"body": body}))

    def create_review(
        self, repo: str, number: int, commit_id: str, body: str, comments: Sequence[ReviewComment]
    ) -> None:
        payload = {
            "commit_id": commit_id,
            "event": "COMMENT",
            "body": body,
            "comments": [comment.payload() for comment in comments],
        }
        url = f"{self._api_url}/repos/{repo}/pulls/{number}/reviews"
        _raise_for_status(self._send("POST", url, json=payload))

    def set_thread_resolved(self, thread_id: str, *, resolved: bool) -> None:
        self._graphql(_RESOLVE if resolved else _UNRESOLVE, {"id": thread_id})

    def _graphql(self, query: str, variables: Mapping[str, object]) -> object:
        response = self._send("POST", self._graphql_url, json={"query": query, "variables": variables})
        _raise_for_status(response)
        body = response.json()
        if isinstance(body, dict) and body.get("errors"):
            raise _GraphQLError(body["errors"])
        return body.get("data") if isinstance(body, dict) else None

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


_MAX_ISSUE_COMMENTS = 20
_MAX_COMMENT_PAGES = 10
_MAX_COMMENT_CHARS = 8000


def _newest_within(bodies: list[str]) -> tuple[str, ...]:
    # Newest first until the budget runs out, then back in reading order: later comments usually settle
    # what earlier ones debated.
    kept: list[str] = []
    used = 0
    for body in reversed(bodies[-_MAX_ISSUE_COMMENTS:]):
        if used + len(body) > _MAX_COMMENT_CHARS:
            # A pasted log must not push every other maintainer comment out.
            continue
        kept.append(body)
        used += len(body)
    return tuple(reversed(kept))


def _counts(comment: _GqlIssueComment, pr_author: str | None) -> bool:
    if comment.is_minimized or comment.author_association not in TRUSTED_ASSOCIATIONS:
        return False
    if comment.author is None:
        return True
    if comment.author.typename == "Bot":
        return False
    return not (comment.author_association == "MEMBER" and comment.author.login == pr_author)


def _first_and_recent(thread: _GqlThread) -> list[_GqlComment]:
    seen = {c.id for c in thread.comments.nodes if c.id}
    return [*thread.comments.nodes, *(c for c in thread.recent.nodes if not c.id or c.id not in seen)]


def _trusted(kind: str, association: str) -> bool:
    """ADR 0008: only bots and people with write access can carry bylaw's state or mute a finding."""
    return kind == "Bot" or association in TRUSTED_ASSOCIATIONS


class GitHubSource:
    def __init__(self, client: GitHubClient, repo: str, number: int) -> None:
        self._client = client
        self._repo = repo.lower()
        self._number = number
        self._base_tree: dict[str, str] | None = None
        self._tree_complete = False

    @property
    def repo(self) -> str:
        return self._repo

    @cached_property
    def _pull(self) -> PullRequest:
        return self._client.pull(self._repo, self._number)

    def info(self) -> ChangeInfo:
        pull = self._pull
        messages = tuple(self._client.pull_commit_messages(self._repo, self._number))
        return ChangeInfo(
            pull.base.sha, pull.head.sha, pull.title, pull.body or "", messages, pull.changed_files
        )

    def changed_files(self) -> tuple[ChangedFile, ...]:
        files: list[ChangedFile] = []
        for item in self._client.pull_files(self._repo, self._number):
            added, missing = parse_patch(item.patch) if item.patch is not None else ((), False)
            omitted = item.patch is None
            changes: int | None = item.changes
            if omitted and changes == 0 and item.status in {"renamed", "copied"} and item.previous_filename:
                # GitHub reports 0 changes both for a pure move and for a binary file that changed on the
                # way; the old blob tells them apart. Two missing shas prove nothing, so that pair is binary.
                before = self._base_blob(item.previous_filename)
                if before is not None and before == item.sha:
                    omitted = False  # moved or copied unchanged: nothing to review
                else:
                    changes = None  # content changed and has no text diff: a binary file
            files.append(
                ChangedFile(
                    path=item.filename,
                    status=_STATUS.get(item.status, "modified"),
                    previous_path=item.previous_filename if item.status == "renamed" else None,
                    added_lines=added,
                    missing_final_newline=missing,
                    patch_omitted=omitted,
                    patch=item.patch or "",
                    changes=changes,
                )
            )
        return tuple(files)

    def _base_blob(self, path: str) -> str | None:
        # One tree read covers every moved file; per-file reads only when GitHub truncates the tree.
        if self._base_tree is None:
            self._base_tree = self._client.tree_shas(self._repo, self._pull.base.sha) or {}
            self._tree_complete = bool(self._base_tree)
        if self._tree_complete:
            return self._base_tree.get(path)
        return self._client.blob_sha(self._repo, path, self._pull.base.sha)

    def read_base(self, path: str) -> str | None:
        return self._client.file_text(self._repo, path, self._pull.base.sha)

    def read_head(self, path: str) -> str | None:
        return self._client.file_text(self._repo, path, self._pull.head.sha)

    def closing_issue_refs(self) -> tuple[IssueRef, ...]:
        return self._client.closing_issue_refs(self._repo, self._number)

    def read_issue(self, ref: IssueRef) -> Issue | None:
        author = self._pull.user.login if self._pull.user else None
        return self._client.issue(ref, exclude=author)
