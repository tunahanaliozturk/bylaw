"""Reads a change from a local repository, for reviewing a branch before a pull request exists."""

import subprocess
from collections.abc import Sequence
from pathlib import Path

from bylaw.diff import parse_unified_diff
from bylaw.model import ChangedFile
from bylaw.source import ChangeInfo, Issue, IssueRef, SourceError


class LocalGitSource:
    """Committed changes from merge-base(base, HEAD) to HEAD. Uncommitted work is not included."""

    def __init__(self, repo_dir: Path, base: str, repo: str | None = None) -> None:
        if base.startswith("-"):
            # git would read it as an option; through the MCP server the base comes from an agent.
            raise SourceError(f"base {base!r} is not a ref: it starts with '-'")
        self._dir = repo_dir
        self._repo = repo.lower() if repo else None
        self._head = self._git("rev-parse", "HEAD").strip()
        self._base = self._git("merge-base", base, self._head).strip()

    @property
    def repo(self) -> str | None:
        return self._repo

    def info(self) -> ChangeInfo:
        # --no-show-signature: log.showSignature in the repository's config would run its gpg.program.
        log = self._git("log", "--no-show-signature", "--format=%B%x00", f"{self._base}..{self._head}")
        messages = tuple(message.strip() for message in log.split("\0") if message.strip())
        return ChangeInfo(self._base, self._head, title="", body="", commit_messages=messages)

    def changed_files(self) -> tuple[ChangedFile, ...]:
        # Explicit prefixes: a user's diff.noprefix or diff.mnemonicPrefix setting would otherwise change
        # the headers the parser reads. --no-ext-diff and --no-textconv: the repository's config can name
        # programs for both, and .gitattributes in the change picks which files they run on.
        diff = self._git(
            "-c",
            "core.quotePath=false",
            "diff",
            "--no-color",
            "--no-ext-diff",
            "--no-textconv",
            "--src-prefix=a/",
            "--dst-prefix=b/",
            "-M",
            self._base,
            self._head,
        )
        return parse_unified_diff(diff)

    def read_base(self, path: str) -> str | None:
        return self._show(self._base, path)

    def read_head(self, path: str) -> str | None:
        return self._show(self._head, path)

    def list_base(self, directory: str) -> frozenset[str]:
        # --full-tree: paths from the repository root, as `git show` reads them, wherever bylaw runs. The
        # trailing slash lists what is inside the directory rather than the directory entry itself.
        paths = ("--", f"{directory}/") if directory else ()
        result = self._run("ls-tree", "-z", "--full-tree", self._base, *paths)
        if result.returncode != 0:
            return frozenset()
        names: set[str] = set()
        for entry in result.stdout.decode("utf-8", errors="replace").split("\0"):
            meta, _, path = entry.partition("\t")
            if meta.split(" ")[1:2] == ["blob"]:
                names.add(path.rpartition("/")[2])
        return frozenset(names)

    def list_base_tree(self, directory: str) -> frozenset[str]:
        paths = ("--", f"{directory}/") if directory else ()
        result = self._run("ls-tree", "-r", "-z", "--full-tree", self._base, *paths)
        if result.returncode != 0:
            return frozenset()
        listing = result.stdout.decode("utf-8", errors="replace")
        entries = (entry.partition("\t") for entry in listing.split("\0"))
        return frozenset(path for meta, _, path in entries if meta.split(" ")[1:2] == ["blob"])

    def read_base_many(self, paths: Sequence[str]) -> dict[str, str | None]:
        return {path: self.read_base(path) for path in paths}

    def closing_issue_refs(self) -> tuple[IssueRef, ...]:
        return ()

    def read_issue(self, ref: IssueRef) -> Issue | None:  # noqa: ARG002 - local mode has no issue API
        return None

    def _show(self, revision: str, path: str) -> str | None:
        # git applies no textconv to `show <rev>:<path>` unless asked; --no-textconv keeps it that way.
        result = self._run("show", "--no-textconv", f"{revision}:{path}")
        return result.stdout.decode("utf-8", errors="replace") if result.returncode == 0 else None

    def _git(self, *args: str) -> str:
        result = self._run(*args)
        if result.returncode != 0:
            message = result.stderr.decode("utf-8", errors="replace").strip()
            raise SourceError(f"git {' '.join(args)} failed: {message}")
        return result.stdout.decode("utf-8", errors="replace")

    def _run(self, *args: str) -> subprocess.CompletedProcess[bytes]:
        # git is resolved from PATH on purpose; arguments are a list, so nothing goes through a shell. No
        # stdin: under `bylaw mcp` it is the protocol channel, and a git that prompts must not read it.
        # core.fsmonitor names a program git starts for commands that look at the work tree. None of
        # bylaw's do (checked with git 2.54: only commands such as `status` start it), so this is a guard
        # for a later git, not a fix with a test.
        return subprocess.run(  # noqa: S603
            ["git", "-c", "core.fsmonitor=false", *args],  # noqa: S607
            cwd=self._dir,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            check=False,
        )
