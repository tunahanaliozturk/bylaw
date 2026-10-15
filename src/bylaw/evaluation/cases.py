"""A case: a base project, the files a pull request changes, and labels for what a review must find."""

import shutil
import subprocess
import tomllib
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from bylaw.context import build_context
from bylaw.local_git import LocalGitSource
from bylaw.model import Category, CriterionStatus, ReviewContext

Kind = Literal["security", "bug", "rule", "requirement", "scope", "clean"]


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


class ExpectedCreep(_Frozen):
    file: str
    line: int


class Case(_Frozen):
    id: str
    project: str
    kind: Kind
    title: str
    message: str
    findings: tuple[ExpectedFinding, ...] = ()
    # A legitimate finding here is neither required nor a false positive.
    allowed: tuple[Span, ...] = ()
    criteria: dict[str, tuple[CriterionStatus, ...]] = Field(default_factory=dict)
    scope_creep: tuple[ExpectedCreep, ...] = ()
    remove: tuple[str, ...] = ()


def load_cases(root: Path) -> tuple[Case, ...]:
    cases: list[Case] = []
    for directory in sorted((root / "cases").iterdir()):
        toml = directory / "case.toml"
        if not toml.is_file():
            continue
        try:
            cases.append(
                Case.model_validate({**tomllib.loads(toml.read_text("utf-8")), "id": directory.name})
            )
        except (tomllib.TOMLDecodeError, ValidationError) as error:
            raise ValueError(f"eval case {directory.name}: {error}") from error
    return tuple(cases)


def build_case_context(root: Path, case: Case, work: Path) -> ReviewContext:
    """Commit the base project, then the change, and collect the context as `bylaw context --base` does."""
    repo = work / case.id
    shutil.copytree(root / "projects" / case.project, repo)
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "base")
    _git(repo, "checkout", "-q", "-b", "change")
    head = root / "cases" / case.id / "head"
    if head.is_dir():
        shutil.copytree(head, repo, dirs_exist_ok=True)
    for path in case.remove:
        (repo / path).unlink()
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", case.message)
    return build_context(LocalGitSource(repo, "main")).model_copy(update={"title": case.title})


def _git(cwd: Path, *args: str) -> None:
    # autocrlf off: a planted tab, trailing space or missing newline must reach the diff byte for byte.
    settings = ["-c", "user.name=bylaw eval", "-c", "user.email=eval@bylaw.invalid"]
    settings += ["-c", "commit.gpgsign=false", "-c", "core.autocrlf=false"]
    subprocess.run(["git", *settings, *args], cwd=cwd, check=True, capture_output=True)  # noqa: S603, S607
