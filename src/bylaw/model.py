"""The contract between bylaw's parts and the hosts that run it. Everything here serialises to JSON."""

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict


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


class RuleSource(_Frozen):
    path: str
    kind: RuleKind
    text: str


class Criterion(_Frozen):
    key: str
    text: str


class Requirement(_Frozen):
    source: str
    title: str
    text: str
    criteria: tuple[Criterion, ...]
    # A reviewer may add inferred criteria (ADR 0011): issues with no checklist or with maintainer comments.
    inferable: bool = False


class Finding(_Frozen):
    file: str
    line_start: int
    line_end: int
    category: Category
    severity: Severity
    message: str
    suggestion: str | None = None
    evidence: str | None = None


class ReviewContext(_Frozen):
    base_sha: str
    head_sha: str
    title: str
    files: tuple[ChangedFile, ...]
    rules: tuple[RuleSource, ...]
    requirements: tuple[Requirement, ...]
    findings: tuple[Finding, ...]
    notes: tuple[str, ...]


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
