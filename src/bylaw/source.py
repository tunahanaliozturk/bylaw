"""Where a review's input comes from. GitHub and local git implement the same protocol."""

from dataclasses import dataclass
from typing import Protocol

from bylaw.model import ChangedFile


class SourceError(Exception):
    """The change could not be read. The message is safe to print."""


@dataclass(frozen=True, slots=True)
class ChangeInfo:
    base_sha: str
    head_sha: str
    title: str
    body: str
    commit_messages: tuple[str, ...]
    # How many files the host says the change touches; GitHub's file listing stops at 3000.
    file_count: int | None = None


@dataclass(frozen=True, slots=True)
class IssueRef:
    owner: str
    repo: str
    number: int

    def label(self, default_repo: str | None) -> str:
        full = f"{self.owner}/{self.repo}"
        if default_repo is not None and full == default_repo.lower():
            return f"issue#{self.number}"
        return f"{full}#{self.number}"


@dataclass(frozen=True, slots=True)
class Issue:
    ref: IssueRef
    title: str
    body: str
    # Trusted authors' comments, oldest first (ADR 0011).
    comments: tuple[str, ...] = ()
    comments_unreadable: bool = False


class RepoSource(Protocol):
    @property
    def repo(self) -> str | None: ...

    def info(self) -> ChangeInfo: ...

    def changed_files(self) -> tuple[ChangedFile, ...]: ...

    def read_base(self, path: str) -> str | None: ...

    def read_head(self, path: str) -> str | None: ...

    def closing_issue_refs(self) -> tuple[IssueRef, ...]: ...

    def read_issue(self, ref: IssueRef) -> Issue | None: ...
