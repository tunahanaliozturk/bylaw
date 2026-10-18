"""Freezes a public pull request into a real evaluation case, so a run never reads live data (ADR 0015)."""

import shutil
import tempfile
from functools import cached_property
from pathlib import Path, PurePosixPath

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
    spdx, name, text = client.licence(repo)
    if spdx not in LICENCES:
        raise ValueError(
            f"{repo} is licensed {spdx or 'unknown'}; only {', '.join(sorted(LICENCES))} may be copied"
        )
    source = PullRequestAt(client, repo, number, commit)
    # Apache-2.0 asks that a NOTICE file travel with copies of the work.
    notice = source.read_base("NOTICE") if spdx == "Apache-2.0" else None
    return freeze(
        source,
        out,
        url=f"https://github.com/{repo}/pull/{number}",
        number=number,
        licence=(spdx, name, text),
        notice=notice,
        evidence=evidence,
    )


def freeze(  # noqa: PLR0913 - what GitHub said about the pull request, all keywords
    source: RepoSource,
    out: Path,
    *,
    url: str,
    number: int,
    licence: tuple[str, str, str],
    notice: str | None = None,
    evidence: ReviewEvidence | None = None,
) -> Snapshot:
    """Write the case directory: what bylaw reads at the base and the head, the issues, the licence."""
    recorder = _Recorder(source)
    build_context(recorder)  # every rule, spec and issue bylaw would read is now recorded
    info = recorder.info()
    patterns = generated_patterns(recorder.read_base(".gitattributes"))
    files = [f for f in recorder.changed_files() if not is_skipped(f.path, patterns)]
    left_out = tuple(f.path for f in recorder.changed_files() if is_skipped(f.path, patterns))
    remove: list[str] = []
    for file in files:
        if file.patch_omitted and file.changes is None:
            raise ValueError(f"{file.path} is binary; the real set takes text changes only")
        if file.status != "added":
            old = file.previous_path or file.path
            if recorder.read_base(old) is None:
                raise ValueError(f"{old} is missing at the base commit")
            if file.status in {"removed", "renamed"}:
                remove.append(old)
        if file.status != "removed" and recorder.read_head(file.path) is None:
            raise ValueError(f"{file.path} is missing at the reviewed commit")
    touched = {f.path for f in files if f.status != "removed"}
    base = {path: text for path, text in recorder.base.items() if text is not None}
    head = {path: text for path, text in recorder.head.items() if text is not None and path in touched}
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
        commit_messages=info.commit_messages,
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
    upstream = {licence_name: licence_text} | ({"NOTICE": notice} if notice is not None else {})
    written = {"base": base, "head": head, ".": upstream}
    for contents in written.values():
        for path in contents:
            _inside(path)
    _clear(out)
    try:
        for part, contents in written.items():
            for path, text in contents.items():
                target = out / part / path
                target.parent.mkdir(parents=True, exist_ok=True)
                # Bytes, not text: a CRLF file must stay CRLF, and Windows must not add any.
                target.write_bytes(text.encode("utf-8"))
        (out / "snapshot.json").write_bytes(pull.model_dump_json(indent=2).encode("utf-8") + b"\n")
        _check_replay(out, pull, files)
    except BaseException:
        _clear(out)
        raise
    return pull


def _clear(out: Path) -> None:
    """Remove what the tool wrote before; the labels in case.toml belong to people and stay."""
    if not out.is_dir():
        return
    for entry in out.iterdir():
        if entry.name == "case.toml":
            continue
        if entry.is_dir():
            shutil.rmtree(entry)
        else:
            entry.unlink()
    if not any(out.iterdir()):
        out.rmdir()


def _inside(path: str) -> None:
    # Paths come from the pull request: one that climbs out would write outside the case directory.
    parts = PurePosixPath(path).parts
    if not parts or PurePosixPath(path).is_absolute() or ".." in parts or ":" in path:
        raise ValueError(f"refusing to write {path!r}: it leaves the case directory")


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
    added = {f.path: [line.number for line in f.added_lines] for f in replayed}
    for file in files:
        if file.status != "removed" and added.get(file.path, []) != [
            line.number for line in file.added_lines
        ]:
            raise ValueError(f"the snapshot does not reproduce the pull request's diff of {file.path}")
