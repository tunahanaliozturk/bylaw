"""The change-management record a compliance profile asks for (ADR 0021).

One record per run, built from what the review already holds, so the summary comment and the evidence
file can never disagree. docs/compliance.md documents every field; a field that changes meaning or goes
away raises SCHEMA_VERSION, a new one does not.
"""

import re
from importlib.metadata import version
from pathlib import PurePosixPath
from typing import Literal

from pydantic import BaseModel, ConfigDict

from bylaw.compliance import load_profile
from bylaw.model import (
    Category,
    CriterionStatus,
    FileStatus,
    Finding,
    ReviewContext,
    ReviewResult,
    Severity,
)
from bylaw.plan import Group, Plan

SCHEMA_VERSION = 1
DISCLAIMER = (
    "bylaw records what its review saw: the tags are the reviewer's judgement, and this is evidence for an "
    "audit, not a compliance verdict."
)
_TEST_DIRECTORIES = frozenset({"test", "tests", "__tests__", "testing"})
# test_x.py, x_test.py, x_test.go, x.test.ts, x.spec.js, XTests.cs, XTest.java and the like.
_TEST_NAME = re.compile(r"^test_.*\.py$|_test\.(py|go)$|\.(test|spec)\.[cm]?[jt]sx?$|Tests?\.(cs|java|kt)$")


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class EvidenceProfile(_Frozen):
    name: str
    standard: str


class EvidenceCriterion(_Frozen):
    key: str
    status: CriterionStatus | Literal["not assessed"]


class EvidenceRequirement(_Frozen):
    # The label only: a work item kept out of quotes must not reach the file through its title (ADR 0014).
    source: str
    criteria: tuple[EvidenceCriterion, ...]


_Status = Literal["open", "accepted", "resolved_by_author"]


class EvidenceFinding(_Frozen):
    file: str
    line_start: int
    line_end: int
    category: Category
    severity: Severity
    message: str
    evidence: str | None
    controls: tuple[str, ...]
    # "resolved_by_author": the pull request's author resolved its thread, which accepts nothing (ADR 0008),
    # so it still counts as open, for `--fail-on` too.
    status: _Status
    # How a person closed it, muted or resolved, and their login when the host says.
    how: Literal["muted", "resolved"] | None = None
    by: str | None = None


class EvidenceFile(_Frozen):
    path: str
    status: FileStatus


class EvidenceControl(_Frozen):
    id: str
    title: str
    # `file:line` of each finding that touches it.
    findings: tuple[str, ...]


class Evidence(_Frozen):
    schema_version: int = SCHEMA_VERSION
    bylaw_version: str
    disclaimer: str = DISCLAIMER
    # Set when the file is written: the summary needs no clock.
    generated_at: str | None = None
    repository: str | None = None
    pull_request: int | None = None
    title: str
    base_sha: str
    head_sha: str
    profiles: tuple[EvidenceProfile, ...]
    # None when the result came from outside `bylaw review`, such as a host model.
    model_review: bool | None
    requirements: tuple[EvidenceRequirement, ...]
    files_changed: tuple[EvidenceFile, ...]
    # The changed files that look like tests, with their status: a removed test is not new coverage.
    tests_changed: tuple[EvidenceFile, ...]
    findings: tuple[EvidenceFinding, ...]
    controls: tuple[EvidenceControl, ...]
    # Threads bylaw resolved this run because their finding is gone from the code.
    threads_resolved: int
    notes: tuple[str, ...]


def is_test(path: str) -> bool:
    pure = PurePosixPath(path)
    return not _TEST_DIRECTORIES.isdisjoint(pure.parts[:-1]) or bool(_TEST_NAME.search(pure.name))


def build_evidence(context: ReviewContext, result: ReviewResult, plan: Plan) -> Evidence:
    findings = [
        *(_open(g) for g in (*plan.inline, *plan.open_threads, *plan.summary_only)),
        *(_accepted(g, "muted") for g in plan.muted),
        *(_accepted(g, "resolved") for g in plan.reviewer_resolved),
        *(_closed(g, "resolved_by_author", "resolved") for g in plan.author_resolved),
    ]
    flat = [entry for group in findings for entry in group]
    profiles = [load_profile(name) for name in context.profiles]
    controls = [
        EvidenceControl(
            id=control.id,
            title=control.title,
            findings=tuple(f"{f.file}:{f.line_start}" for f in flat if control.id in f.controls),
        )
        for profile in profiles
        for control in profile.controls
    ]
    changed = tuple(EvidenceFile(path=f.path, status=f.status) for f in context.files)
    return Evidence(
        bylaw_version=version("bylaw"),
        title=context.title,
        base_sha=context.base_sha,
        head_sha=context.head_sha,
        profiles=tuple(EvidenceProfile(name=p.name, standard=p.standard) for p in profiles),
        model_review=context.model_review,
        requirements=_requirements(context, result),
        files_changed=changed,
        tests_changed=tuple(f for f in changed if is_test(f.path)),
        findings=tuple(flat),
        controls=tuple(control for control in controls if control.findings),
        threads_resolved=len(plan.resolve),
        notes=(*context.notes, *plan.notes),
    )


def _requirements(context: ReviewContext, result: ReviewResult) -> tuple[EvidenceRequirement, ...]:
    statuses = {item.criterion: item.status for item in result.criteria}
    requirements: list[EvidenceRequirement] = []
    for requirement in context.requirements:
        keys = [f"{requirement.source}/{c.key}" for c in requirement.criteria]
        # Criteria the reviewer inferred from prose (ADR 0011) count as well.
        keys += sorted(k for k in statuses if k.startswith(f"{requirement.source}/IC-"))
        criteria = tuple(EvidenceCriterion(key=k, status=statuses.get(k, "not assessed")) for k in keys)
        requirements.append(EvidenceRequirement(source=requirement.source, criteria=criteria))
    return tuple(requirements)


def _open(group: Group) -> list[EvidenceFinding]:
    return [_entry(f, "open") for f in (group.finding, *group.others)]


def _accepted(group: Group, how: Literal["muted", "resolved"]) -> list[EvidenceFinding]:
    return _closed(group, "accepted", how)


def _closed(group: Group, status: _Status, how: Literal["muted", "resolved"]) -> list[EvidenceFinding]:
    return [
        _entry(f, status).model_copy(update={"how": how, "by": group.by})
        for f in (group.finding, *group.others)
    ]


def _entry(finding: Finding, status: _Status) -> EvidenceFinding:
    return EvidenceFinding(
        file=finding.file,
        line_start=finding.line_start,
        line_end=finding.line_end,
        category=finding.category,
        severity=finding.severity,
        message=finding.message,
        evidence=finding.evidence,
        controls=finding.controls,
        status=status,
    )
