"""The contract between bylaw's parts and the hosts that run it. Everything here serialises to JSON."""

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


def text_lines(text: str) -> list[str]:
    """Lines as GitHub and editors number them, which is what evidence like `CONTRIBUTING.md:12` means.

    Only a newline ends a line, and a carriage return before it belongs to the break. str.splitlines()
    also breaks at form feeds, U+2028 and others, so its numbers drift from the file's.
    """
    lines = text.split("\n")
    if lines[-1] == "":
        lines.pop()
    return [line.removesuffix("\r") for line in lines]


class Category(StrEnum):
    SECURITY = "security"
    BUG = "bug"
    RULE = "rule"
    REQUIREMENT = "requirement"


class Severity(StrEnum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    SUGGESTION = "suggestion"


class RuleKind(StrEnum):
    EDITORCONFIG = "editorconfig"
    LINTER = "linter"
    PROSE = "prose"


# Every note about a model review that did not happen starts with this, so the summary can tell.
MODEL_NOT_RUN = "The model review did not run"

FileStatus = Literal["added", "modified", "renamed", "removed"]


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class AddedLine(_Frozen):
    number: int
    text: str


class ChangedFile(_Frozen):
    path: str
    status: FileStatus
    previous_path: str | None = None
    added_lines: tuple[AddedLine, ...] = ()
    missing_final_newline: bool = False
    patch_omitted: bool = False
    patch: str = ""
    # Lines added plus removed as the host counts them; None when the diff came from local git.
    changes: int | None = None


class FileRules(_Frozen):
    """Rule ids a linter turns on or off for the files a glob matches, relative to its config's directory."""

    pattern: str
    select: tuple[str, ...] = ()
    ignore: tuple[str, ...] = ()


class LinterRules(_Frozen):
    """The rule ids a linter configuration enables, read without running anything (ADR 0013)."""

    tool: str
    # Ruff selectors are code prefixes; for the other tools these are exact ids, "*" meaning all.
    select: tuple[str, ...] = ()
    ignore: tuple[str, ...] = ()
    per_file: tuple[FileRules, ...] = ()
    # What the configuration says that bylaw cannot turn into ids, such as an `extends`.
    notes: tuple[str, ...] = ()
    # False when it inherits or sets something bylaw did not read, so its silence on an id proves nothing.
    complete: bool = True


class RuleSource(_Frozen):
    path: str
    kind: RuleKind
    text: str
    # The directory whose files the rule applies to, "" for the whole repository (ADR 0013).
    directory: str = ""
    linter: LinterRules | None = None


class Criterion(_Frozen):
    key: str
    text: str


class Requirement(_Frozen):
    source: str
    title: str
    text: str
    criteria: tuple[Criterion, ...]
    # Trusted authors' comments on a linked issue, kept apart from the text so the text cannot pose as one.
    comments: tuple[str, ...] = ()
    # A reviewer may add inferred criteria (ADR 0011): issues with no checklist or with maintainer comments.
    inferable: bool = False
    # False keeps the text out of public comments: the summary shows criterion keys and status (ADR 0014).
    quoted: bool = True


class Decision(_Frozen):
    """An accepted ADR from the base branch: the reviewer sees its title, status and decision (ADR 0016)."""

    path: str
    title: str
    status: str
    # The file's line the shown text starts on, so a finding cites the ADR's own line numbers.
    start: int
    text: str
    # The directory whose files it binds, "" for the whole repository: a package's own ADRs bind only it.
    directory: str = ""
    # True when the decision was longer than its share of the brief and only its start is shown.
    cut: bool = False


class Finding(_Frozen):
    file: str
    line_start: int
    line_end: int
    category: Category
    severity: Severity
    message: str
    suggestion: str | None = None
    evidence: str | None = None
    # Ids of the compliance profile controls the finding touches, such as "8.28" (ADR 0021).
    controls: tuple[str, ...] = ()


class ReviewContext(_Frozen):
    base_sha: str
    head_sha: str
    title: str
    files: tuple[ChangedFile, ...]
    rules: tuple[RuleSource, ...]
    requirements: tuple[Requirement, ...]
    findings: tuple[Finding, ...]
    notes: tuple[str, ...]
    # From .bylaw.toml on the base branch, so a preview made from this file matches what would be posted.
    severity_threshold: Severity = Severity.MEDIUM
    max_comments: int = 15
    input_tokens: int = 300_000
    # Files an incremental review leaves out because their change is the same as at the last run.
    carried_over: tuple[str, ...] = ()
    # Accepted ADRs the change is held to, newest first (ADR 0016).
    decisions: tuple[Decision, ...] = ()
    # Compliance profiles from the base branch's .bylaw.toml, by name (ADR 0021).
    profiles: tuple[str, ...] = ()


class CriterionStatus(StrEnum):
    MET = "met"
    PARTIAL = "partial"
    MISSING = "missing"


class Location(_Frozen):
    file: str
    line: int


class CriterionResult(_Frozen):
    criterion: str
    status: CriterionStatus
    # The criterion itself, for one the reviewer inferred from a requirement written as prose.
    text: str | None = None
    code: tuple[Location, ...] = ()
    tests: tuple[Location, ...] = ()
    note: str = ""


class ScopeCreep(_Frozen):
    file: str
    line: int
    message: str


class ReviewResult(_Frozen):
    findings: tuple[Finding, ...] = ()
    criteria: tuple[CriterionResult, ...] = ()
    scope_creep: tuple[ScopeCreep, ...] = ()


class ReviewMemory(_Frozen):
    """What the last model review saw and said, kept so the next run can skip what did not change."""

    head_sha: str
    inputs: str
    # Path to the hash of its change, for the files the model actually read.
    files: dict[str, str] = Field(default_factory=dict)
    findings: tuple[Finding, ...] = ()
    criteria: tuple[CriterionResult, ...] = ()
    scope_creep: tuple[ScopeCreep, ...] = ()
    # Criterion key to the head the model last assessed it on.
    criteria_since: dict[str, str] = Field(default_factory=dict)
    # Model tokens, input plus output: on this pull request so far, and in the run that wrote this.
    tokens: int = 0
    run_tokens: int = 0
