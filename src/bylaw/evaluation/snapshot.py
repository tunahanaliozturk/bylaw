"""Freezes a public pull request into a real evaluation case, so a run never reads live data (ADR 0015)."""

import re
import shutil
import tempfile
from collections.abc import Sequence
from functools import cached_property
from pathlib import Path

from bylaw.context import build_context, generated_patterns, is_skipped
from bylaw.evaluation.cases import (
    FIRST_PASS,
    Case,
    FrozenIssue,
    IssueKey,
    ReviewEvidence,
    Snapshot,
    build_case_context,
)
from bylaw.github import Comparison, GitHubClient, GitHubSource
from bylaw.model import ChangedFile
from bylaw.source import ChangeInfo, Issue, IssueRef, RepoSource

# The licences that allow copying a project's files into this repository with their notice.
LICENCES = frozenset({"MIT", "Apache-2.0", "BSD-2-Clause", "BSD-3-Clause"})
# "About 60 KB" per touched file, as the selection rules say (docs/eval/real-set.md).
MAX_FILE_BYTES = 60 * 1024


class PullRequestAt(GitHubSource):
    """A pull request as it stood at one of its commits, diffed from the merge base as GitHub showed it."""

    def __init__(self, client: GitHubClient, repo: str, number: int, commit: str | None = None) -> None:
        super().__init__(client, repo, number)
        self._commit = commit

    @cached_property
    def _comparison(self) -> Comparison:
        return self._client.compare(self._repo, self._pull.base.sha, self._commit or self._pull.head.sha)

    @property
    def _base_sha(self) -> str:
        return self._comparison.merge_base_commit.sha

    @property
    def _head_sha(self) -> str:
        return self._commit or self._pull.head.sha

    def info(self) -> ChangeInfo:
        return ChangeInfo(
            self._base_sha,
            self._head_sha,
            self._pull.title,
            self._pull.body or "",
            tuple(c.commit.message for c in self._comparison.commits),
        )

    def changed_files(self) -> tuple[ChangedFile, ...]:
        return self._changed(self._comparison.files)

    def read_base(self, path: str) -> str | None:
        # bylaw looks for a dozen rule files most projects lack; the one tree read answers all of them.
        tree = self._tree()
        if tree is not None and path not in tree:
            return None
        return super().read_base(path)


class _Recorder:
    """Passes every read through to the live source and keeps what bylaw asked for."""

    def __init__(self, source: RepoSource) -> None:
        self._source = source
        self.base: dict[str, str | None] = {}
        self.head: dict[str, str | None] = {}
        self.issues: dict[IssueRef, Issue | None] = {}

    @property
    def repo(self) -> str | None:
        return self._source.repo

    @cached_property
    def _info(self) -> ChangeInfo:
        return self._source.info()

    def info(self) -> ChangeInfo:
        return self._info

    @cached_property
    def _files(self) -> tuple[ChangedFile, ...]:
        return self._source.changed_files()

    def changed_files(self) -> tuple[ChangedFile, ...]:
        return self._files

    def list_base(self, directory: str) -> frozenset[str]:
        # Not recorded: a replay lists the snapshot's own base, which holds every file bylaw read.
        return self._source.list_base(directory)

    def list_base_tree(self, directory: str) -> frozenset[str]:
        return self._source.list_base_tree(directory)

    def read_base_many(self, paths: Sequence[str]) -> dict[str, str | None]:
        missing = [path for path in paths if path not in self.base]
        if missing:
            self.base.update(self._source.read_base_many(missing))
        return {path: self.base[path] for path in paths}

    def read_base(self, path: str) -> str | None:
        if path not in self.base:
            self.base[path] = self._source.read_base(path)
        return self.base[path]

    def read_head(self, path: str) -> str | None:
        if path not in self.head:
            self.head[path] = self._source.read_head(path)
        return self.head[path]

    @cached_property
    def _closing(self) -> tuple[IssueRef, ...]:
        return self._source.closing_issue_refs()

    def closing_issue_refs(self) -> tuple[IssueRef, ...]:
        return self._closing

    def read_issue(self, ref: IssueRef) -> Issue | None:
        if ref not in self.issues:
            self.issues[ref] = self._source.read_issue(ref)
        return self.issues[ref]


def snapshot_pull_request(
    client: GitHubClient, repo: str, number: int, comment_id: int | None, out: Path
) -> Snapshot:
    """Read a pull request at the commit a review comment was made on (or its head) and freeze it."""
    _case_id(out)  # before any call to GitHub
    evidence: ReviewEvidence | None = None
    commit: str | None = None
    if comment_id is not None:
        comment = client.pull_comment(repo, comment_id)
        on = comment.pull_request_url.rstrip("/").rpartition("/")[2]
        if on != str(number):
            raise ValueError(f"comment {comment_id} belongs to pull request {on}, not {number}")
        commit = comment.original_commit_id
        line = comment.original_line or 1
        evidence = ReviewEvidence(
            url=comment.html_url,
            path=comment.path,
            lines=(comment.original_start_line or line, line),
            body=comment.body,
        )
    source = PullRequestAt(client, repo, number, commit)
    # The licence of the commit the files are copied from: a project can relicense later.
    spdx, name, text = client.licence(repo, source.info().base_sha)
    if spdx not in LICENCES:
        raise ValueError(
            f"{repo} is licensed {spdx or 'unknown'} at the base commit; only "
            f"{', '.join(sorted(LICENCES))} may be copied"
        )
    # Apache-2.0 asks that NOTICE files travel with copies of the work; they cost nothing elsewhere.
    notices = {
        n: t
        for n in sorted(source.list_base(""))
        if n.upper().startswith("NOTICE") and (t := source.read_base(n)) is not None
    }
    return freeze(
        source,
        out,
        url=f"https://github.com/{repo}/pull/{number}",
        number=number,
        licence=(spdx, name, text),
        notices=notices,
        evidence=evidence,
    )


def freeze(  # noqa: PLR0913 - what GitHub said about the pull request, all keywords
    source: RepoSource,
    out: Path,
    *,
    url: str,
    number: int,
    licence: tuple[str, str, str],
    notices: dict[str, str] | None = None,
    evidence: ReviewEvidence | None = None,
) -> Snapshot:
    """Write the case directory: what bylaw reads at the base and the head, the issues, the licence."""
    _case_id(out)
    recorder = _Recorder(source)
    build_context(recorder, env={})  # every rule, spec and issue bylaw would read is now recorded
    info = recorder.info()
    patterns = generated_patterns(recorder.read_base(".gitattributes"))
    files = [f for f in recorder.changed_files() if not is_skipped(f.path, patterns)]
    left_out = tuple(f.path for f in recorder.changed_files() if is_skipped(f.path, patterns))
    remove = _check_changes(recorder, files)
    touched = {f.path for f in files if f.status != "removed"}
    base = {path: text for path, text in recorder.base.items() if text is not None}
    head = {path: text for path, text in recorder.head.items() if text is not None and path in touched}
    _check_texts(files, base, head)
    _check_file_licences(files, base, head, licence[0])
    # A spec read at the head that the change does not touch is the same at the base.
    base |= {p: t for p, t in recorder.head.items() if t is not None and p not in touched}
    spdx, licence_name, licence_text = licence
    pull = Snapshot(
        repo=recorder.repo or "",
        number=number,
        url=url,
        licence=spdx,
        base_sha=info.base_sha,
        head_sha=info.head_sha,
        title=info.title,
        body=info.body,
        commit_messages=tuple(_scrub(m) for m in info.commit_messages),
        closing=tuple(
            IssueKey(owner=r.owner, repo=r.repo, number=r.number) for r in recorder.closing_issue_refs()
        ),
        issues=tuple(
            FrozenIssue(
                owner=ref.owner,
                repo=ref.repo,
                number=ref.number,
                title=issue.title,
                body=issue.body,
                comments=issue.comments,
                comments_unreadable=issue.comments_unreadable,
            )
            for ref, issue in recorder.issues.items()
            if issue is not None
        ),
        remove=tuple(remove),
        left_out=left_out,
        evidence=evidence,
    )
    upstream = {licence_name: licence_text} | (notices or {})
    written = {"base": base, "head": head, ".": upstream}
    for contents in written.values():
        for path in contents:
            _inside(path)
    # Written next to the case and moved into place only once the replay matches, so a failed freeze
    # leaves the previous snapshot as it was.
    out.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{out.name}.", dir=out.parent))
    try:
        for part, contents in written.items():
            for path, text in contents.items():
                target = staging / part / path
                if not target.resolve().is_relative_to(staging.resolve()):
                    raise ValueError(f"refusing to write {path!r}: it leaves the case directory")
                target.parent.mkdir(parents=True, exist_ok=True)
                # Bytes, not text: a CRLF file must stay CRLF, and Windows must not add any.
                target.write_bytes(text.encode("utf-8"))
        (staging / "snapshot.json").write_bytes(pull.model_dump_json(indent=2).encode("utf-8") + b"\n")
        _check_replay(staging, pull, files)
        _replace(out, staging)
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    return pull


def _check_changes(recorder: _Recorder, files: list[ChangedFile]) -> list[str]:
    """Read both ends of every change and refuse what cannot be frozen; return the paths to remove."""
    remove: list[str] = []
    for file in files:
        # A pure move has a patch-free entry that is not omitted; anything else without a patch is binary,
        # or too large for GitHub to diff, and would be frozen as corrupted text.
        if file.patch_omitted and file.status != "removed":
            raise ValueError(f"{file.path} has no text diff; the real set takes text changes only")
        if file.status != "added":
            old = file.previous_path or file.path
            if recorder.read_base(old) is None:
                raise ValueError(f"{old} is missing at the base commit")
            if file.status in {"removed", "renamed"}:
                remove.append(old)
        if file.status != "removed" and recorder.read_head(file.path) is None:
            raise ValueError(f"{file.path} is missing at the reviewed commit")
    return remove


_TRAILER = re.compile(r"^[A-Za-z][\w-]*-by:.*(?:\n|$)", re.MULTILINE)
_EMAIL = re.compile(r"<?[\w.+-]+@[\w-]+(?:\.[\w-]+)+>?")


def _scrub(message: str) -> str:
    """Drop Signed-off-by style trailers and email addresses: personal data bylaw never reads."""
    text = _EMAIL.sub("<email removed>", _TRAILER.sub("", message))
    return re.sub(r"\n{3,}", "\n\n", text).strip()


_SPDX = re.compile(r"SPDX-License-Identifier:\s*([^\s*/]+)")
_COPYLEFT = re.compile(
    r"GNU\s+(Lesser\s+|Library\s+|Affero\s+)?General\s+Public|Mozilla\s+Public\s+Licen[cs]e", re.I
)
_HEADER_LINES = 50


def _check_file_licences(
    files: list[ChangedFile], base: dict[str, str], head: dict[str, str], spdx: str
) -> None:
    """A permissive project can still vendor a file under another licence; its header says so."""
    for path in {f.path for f in files} | {f.previous_path for f in files if f.previous_path}:
        for side in (base.get(path), head.get(path)):
            header = "\n".join((side or "").splitlines()[:_HEADER_LINES])
            named = _SPDX.search(header)
            if (named and named[1] != spdx) or _COPYLEFT.search(header):
                raise ValueError(f"{path} carries its own licence, not {spdx}; it cannot be copied")


def _check_texts(files: list[ChangedFile], base: dict[str, str], head: dict[str, str]) -> None:
    for path, text in (*base.items(), *head.items()):
        # GitHub's text reads replace bytes that are not UTF-8; a NUL means a binary file slipped through.
        if "\0" in text or "\ufffd" in text:
            raise ValueError(f"{path} is not UTF-8 text; the real set takes text files only")
    for path in {f.path for f in files} | {f.previous_path for f in files if f.previous_path}:
        for side in (base.get(path), head.get(path)):
            if side is not None and len(side.encode("utf-8")) > MAX_FILE_BYTES:
                raise ValueError(f"{path} is over {MAX_FILE_BYTES // 1024} KB, the real set's cap per file")


def _replace(out: Path, staging: Path) -> None:
    """Swap the new snapshot in; the labels in case.toml belong to people and move across."""
    if (out / "case.toml").is_file():
        shutil.copy(out / "case.toml", staging / "case.toml")
    if out.exists():
        old = staging.with_name(f"{staging.name}.old")
        out.rename(old)
        staging.rename(out)
        shutil.rmtree(old)
    else:
        staging.rename(out)


_CASE_ID = re.compile(r"[a-z0-9][a-z0-9._-]*")
# Names Windows reserves in every directory, with or without an extension.
_DEVICES = re.compile(r"(con|prn|aux|nul|com[0-9]|lpt[0-9])(\..*)?", re.IGNORECASE)


def _case_id(out: Path) -> None:
    # The parent check catches "." and "": Path drops them, and the set's cases directory would be wiped.
    if out.parent.name != "cases" or not _CASE_ID.fullmatch(out.name):
        raise ValueError(f"case id {out.name!r} must be lower-case letters, digits, '.', '_' or '-'")


def _inside(path: str) -> None:
    # Paths come from the pull request, and a git tree allows names Windows reads as a way out.
    parts = path.split("/")
    if any(c in path for c in "\\:\0") or any(
        p in {"", ".", ".."} or p != p.rstrip(". ") or _DEVICES.fullmatch(p) for p in parts
    ):
        raise ValueError(f"refusing to write {path!r}: it leaves the case directory or cannot exist")


def _check_replay(out: Path, pull: Snapshot, files: list[ChangedFile]) -> None:
    """Build the case as a run would and compare its diff with GitHub's, line for line."""
    case = Case(
        id=out.name,
        kind="clean",
        title=pull.title,
        message=pull.title,
        remove=pull.remove,
        pull_request=pull,
        labellers=(FIRST_PASS,),
    )
    with tempfile.TemporaryDirectory() as work:
        replayed = build_case_context(out.parent.parent, case, Path(work)).files
    if extra := sorted({f.path for f in replayed} ^ {f.path for f in files}):
        raise ValueError(f"the snapshot does not reproduce the pull request's diff of {', '.join(extra)}")
    added = {f.path: f.added_lines for f in replayed}
    for file in files:
        if file.status != "removed" and added.get(file.path, ()) != file.added_lines:
            raise ValueError(f"the snapshot does not reproduce the pull request's diff of {file.path}")
