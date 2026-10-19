"""A case: a base project, the files a pull request changes, and labels for what a review must find."""

import hashlib
import os
import shutil
import subprocess
import tomllib
from dataclasses import replace
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from bylaw.context import build_context
from bylaw.local_git import LocalGitSource
from bylaw.model import Category, CriterionStatus, ReviewContext
from bylaw.source import ChangeInfo, Issue, IssueRef

Kind = Literal["security", "bug", "rule", "requirement", "scope", "clean"]
# A model's first pass is a draft for the people who label a real case; it never makes the labels final.
FIRST_PASS = "first pass (model)"  # noqa: S105 - a labeller name, not a secret


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Span(_Frozen):
    file: str
    lines: tuple[int, int]


class ExpectedFinding(Span):
    categories: tuple[Category, ...]
    note: str
    evidence: str | None = None
    # Found by bylaw's own checks (.editorconfig), with or without a model.
    deterministic: bool = False
    # Other places where a reviewer may fairly anchor the same defect, such as the call of a broken method.
    also: tuple[Span, ...] = ()
    # Profile controls a right answer may tag, in a project with a compliance profile on (ADR 0021).
    controls: tuple[str, ...] = ()


class ExpectedCreep(_Frozen):
    file: str
    line: int


class IssueKey(_Frozen):
    owner: str
    repo: str
    number: int


class FrozenIssue(IssueKey):
    title: str
    body: str
    comments: tuple[str, ...] = ()
    comments_unreadable: bool = False


class ReviewEvidence(_Frozen):
    """The review comment a real case is built around. Labellers read it; the reviewer never sees it."""

    url: str
    path: str
    lines: tuple[int, int]
    body: str


class Snapshot(_Frozen):
    """What `bylaw eval snapshot` froze: the pull request as the reviewer saw it, and what GitHub said."""

    repo: str
    number: int
    url: str
    licence: str
    # The merge base and the reviewed commit, which is what GitHub diffed for the reviewer.
    base_sha: str
    head_sha: str
    title: str
    body: str = ""
    commit_messages: tuple[str, ...] = ()
    closing: tuple[IssueKey, ...] = ()
    issues: tuple[FrozenIssue, ...] = ()
    remove: tuple[str, ...] = ()
    # Changed files bylaw skips anyway (lockfiles, vendored, generated), left out to keep the snapshot small.
    left_out: tuple[str, ...] = ()
    evidence: ReviewEvidence | None = None


class Disagreement(_Frozen):
    """Where two labellers of a real case differed, and what the case says now."""

    about: str
    views: dict[str, str]
    resolution: str


class Case(_Frozen):
    id: str
    # A planted case names its base project; a real one carries its frozen pull request instead.
    project: str = ""
    pull_request: Snapshot | None = None
    labellers: tuple[str, ...] = ()
    disagreements: tuple[Disagreement, ...] = ()
    kind: Kind
    title: str
    message: str
    findings: tuple[ExpectedFinding, ...] = ()
    # A legitimate finding here is neither required nor a false positive.
    allowed: tuple[Span, ...] = ()
    criteria: dict[str, tuple[CriterionStatus, ...]] = Field(default_factory=dict)
    scope_creep: tuple[ExpectedCreep, ...] = ()
    remove: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _labels_fit_the_kind(self) -> "Case":
        labelled = {
            "security": bool(self.findings),
            "bug": bool(self.findings),
            "rule": bool(self.findings),
            "requirement": bool(self.criteria),
            "scope": bool(self.scope_creep),
            "clean": not (self.findings or self.criteria or self.scope_creep),
        }
        if not labelled[self.kind]:
            raise ValueError(f"the labels do not fit a {self.kind} case")
        if bool(self.project) == (self.pull_request is not None):
            raise ValueError("a case names a project or carries a snapshot.json, not both")
        if self.pull_request is not None and not self.labellers:
            raise ValueError("a real case names its labellers")
        for disagreement in self.disagreements:
            if strangers := sorted(set(disagreement.views) - set(self.labellers)):
                raise ValueError(f"{disagreement.about}: {', '.join(strangers)} did not label this case")
        return self

    @property
    def provisional(self) -> bool:
        """A real case two people have not labelled yet: reported, never counted as a measurement."""
        # A draft left in the list means someone has not finished replacing it (docs/eval/labelling.md).
        draft = FIRST_PASS in self.labellers or len(set(self.labellers)) < 2  # noqa: PLR2004 - two labellers
        return self.pull_request is not None and draft


def load_cases(root: Path) -> tuple[Case, ...]:
    cases: list[Case] = []
    for directory in sorted(d for d in (root / "cases").iterdir() if d.is_dir()):
        toml = directory / "case.toml"
        if not toml.is_file():
            raise ValueError(f"eval case {directory.name}: no case.toml")
        try:
            data = {**tomllib.loads(toml.read_text("utf-8")), "id": directory.name}
            frozen = directory / "snapshot.json"
            if frozen.is_file():
                pull = Snapshot.model_validate_json(frozen.read_bytes())
                data |= {
                    "title": pull.title,
                    "message": pull.title,
                    "remove": pull.remove,
                    "pull_request": pull,
                }
            cases.append(Case.model_validate(data))
        except (tomllib.TOMLDecodeError, ValidationError) as error:
            raise ValueError(f"eval case {directory.name}: {error}") from error
    return tuple(cases)


def build_case_context(root: Path, case: Case, work: Path) -> ReviewContext:
    """Commit the base project, then the change, and collect the context as `bylaw context --base` does."""
    base = _base_directory(root, case)
    if case.pull_request is None and not base.is_dir():
        raise ValueError(f"eval case {case.id}: project {case.project} does not exist")
    repo = work / case.id
    repo.mkdir(parents=True)
    if base.is_dir():
        shutil.copytree(base, repo, dirs_exist_ok=True, copy_function=shutil.copy)
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "add", "-A")
    # Empty commits allowed: a real pull request may add every file it touches to a base with no rules.
    _git(repo, "commit", "-q", "--allow-empty", "-m", "base")
    _git(repo, "checkout", "-q", "-b", "change")
    head = root / "cases" / case.id / "head"
    if head.is_dir():
        # shutil.copy, not copy2: a kept mtime older than git's index hides a same-size edit from `git add`.
        shutil.copytree(head, repo, dirs_exist_ok=True, copy_function=shutil.copy)
    for path in case.remove:
        (repo / path).unlink()
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "--allow-empty", "-m", case.message)
    source = LocalGitSource(repo, "main") if case.pull_request is None else _Replay(repo, case.pull_request)
    # No environment: a frozen .bylaw.toml from another project must never reach a tracker with the
    # developer's tokens, so an evaluation run reads nothing but the case.
    return build_context(source, env={}).model_copy(update={"title": case.title})


def _base_directory(root: Path, case: Case) -> Path:
    return (
        root / "projects" / case.project if case.pull_request is None else root / "cases" / case.id / "base"
    )


class _Replay(LocalGitSource):
    """A frozen pull request: git for the files, the snapshot for what GitHub said. Never the network."""

    def __init__(self, repo_dir: Path, pull: Snapshot) -> None:
        super().__init__(repo_dir, "main", pull.repo)
        self._pull = pull

    def info(self) -> ChangeInfo:
        return replace(
            super().info(),
            title=self._pull.title,
            body=self._pull.body,
            commit_messages=self._pull.commit_messages,
        )

    def closing_issue_refs(self) -> tuple[IssueRef, ...]:
        return tuple(IssueRef(key.owner, key.repo, key.number) for key in self._pull.closing)

    def read_issue(self, ref: IssueRef) -> Issue | None:
        for issue in self._pull.issues:
            if IssueRef(issue.owner, issue.repo, issue.number) == ref:
                return Issue(ref, issue.title, issue.body, issue.comments, issue.comments_unreadable)
        return None


def _git(cwd: Path, *args: str) -> None:
    # autocrlf off: a planted tab, trailing space or missing newline must reach the diff byte for byte.
    settings = ["-c", "user.name=bylaw eval", "-c", "user.email=eval@bylaw.invalid"]
    settings += ["-c", "commit.gpgsign=false", "-c", "core.autocrlf=false"]
    # The user's own hooks have no business in a throwaway repository, and a failing one would end the run.
    settings += ["-c", f"core.hooksPath={os.devnull}"]
    subprocess.run(["git", *settings, *args], cwd=cwd, check=True, capture_output=True)  # noqa: S603, S607


def case_digest(root: Path, case: Case) -> str:
    """A hash of everything a case is built from, so a saved review of an older version is not reused."""
    digest = hashlib.sha256()
    own = root / "cases" / case.id
    for directory in (own,) if case.pull_request else (root / "projects" / case.project, own):
        for path in sorted(p for p in directory.rglob("*") if p.is_file()):
            digest.update(path.relative_to(root).as_posix().encode() + b"\0" + path.read_bytes() + b"\0")
    return digest.hexdigest()
