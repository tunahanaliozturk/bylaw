"""Reads a change from a local repository, for reviewing a branch before a pull request exists."""

import subprocess
from pathlib import Path

from bylaw.diff import parse_unified_diff
from bylaw.model import ChangedFile
from bylaw.source import ChangeInfo, Issue, IssueRef, SourceError


class LocalGitSource:
    """Committed changes from merge-base(base, HEAD) to HEAD. Uncommitted work is not included."""

    def __init__(self, repo_dir: Path, base: str, repo: str | None = None) -> None:
        self._dir = repo_dir
        self._repo = repo.lower() if repo else None
        self._head = self._git("rev-parse", "HEAD").strip()
        self._base = self._git("merge-base", base, self._head).strip()

    @property
    def repo(self) -> str | None:
        return self._repo

    def info(self) -> ChangeInfo:
        log = self._git("log", "--format=%B%x00", f"{self._base}..{self._head}")
        messages = tuple(message.strip() for message in log.split("\0") if message.strip())
        return ChangeInfo(self._base, self._head, title="", body="", commit_messages=messages)

    def changed_files(self) -> tuple[ChangedFile, ...]:
        diff = self._git(
            "-c", "core.quotePath=false", "diff", "--no-color", "--no-ext-diff", "-M", self._base, self._head
        )
        return parse_unified_diff(diff)

    def read_base(self, path: str) -> str | None:
        return self._show(self._base, path)

    def read_head(self, path: str) -> str | None:
        return self._show(self._head, path)

    def closing_issue_refs(self) -> tuple[IssueRef, ...]:
        return ()

    def read_issue(self, ref: IssueRef) -> Issue | None:  # noqa: ARG002 - local mode has no issue API
        return None

    def _show(self, revision: str, path: str) -> str | None:
        result = self._run("show", f"{revision}:{path}")
        return result.stdout.decode("utf-8", errors="replace") if result.returncode == 0 else None

    def _git(self, *args: str) -> str:
        result = self._run(*args)
        if result.returncode != 0:
            message = result.stderr.decode("utf-8", errors="replace").strip()
            raise SourceError(f"git {' '.join(args)} failed: {message}")
        return result.stdout.decode("utf-8", errors="replace")

    def _run(self, *args: str) -> subprocess.CompletedProcess[bytes]:
        # git is resolved from PATH on purpose; arguments are a list, so nothing goes through a shell.
        return subprocess.run(["git", *args], cwd=self._dir, capture_output=True, check=False)  # noqa: S603, S607
