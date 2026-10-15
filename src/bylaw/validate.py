"""Drops what the review context cannot back up. Runs on every result, whoever produced it."""

import re
from dataclasses import dataclass

from bylaw.model import Category, CriterionResult, Finding, Location, ReviewContext, ReviewResult, ScopeCreep

_NEEDS_EVIDENCE = frozenset({Category.RULE, Category.REQUIREMENT})
INFERRED_LIMIT = 5
INFERRED_TEXT_LIMIT = 300
_INFERRED = re.compile(r"IC-([1-9][0-9]*)")


@dataclass(frozen=True, slots=True)
class Validated:
    result: ReviewResult
    dropped: tuple[str, ...]


def validate(context: ReviewContext, result: ReviewResult) -> Validated:
    checker = _Checker(context)
    dropped: list[str] = []
    # Inferred criteria first, so a requirement finding may cite one.
    checker.criteria |= {item.criterion for item in result.criteria if checker.inferred_problem(item) is None}

    findings: list[Finding] = []
    seen: set[tuple[str, int, int, Category]] = set()
    for finding in result.findings:
        key = (finding.file, finding.line_start, finding.line_end, finding.category)
        problem = checker.finding_problem(finding)
        if problem is None and key in seen:
            problem = "duplicates another finding on the same lines"
        if problem is not None:
            dropped.append(f"{finding.file}:{finding.line_start} {finding.category}: {problem}")
            continue
        seen.add(key)
        findings.append(finding)

    criteria: list[CriterionResult] = []
    assessed: set[str] = set()
    for item in result.criteria:
        if item.criterion not in checker.criteria:
            dropped.append(
                f"{item.criterion}: {checker.inferred_problem(item) or 'no such acceptance criterion'}"
            )
            continue
        if item.criterion in assessed:
            dropped.append(f"{item.criterion}: duplicate criterion result")
            continue
        assessed.add(item.criterion)
        code = tuple(location for location in item.code if checker.in_change(location))
        tests = tuple(location for location in item.tests if checker.in_change(location))
        if lost := len(item.code) + len(item.tests) - len(code) - len(tests):
            dropped.append(f"{item.criterion}: {lost} location(s) outside the change")
        criteria.append(item.model_copy(update={"code": code, "tests": tests}))

    scope: list[ScopeCreep] = []
    for entry in result.scope_creep:
        if checker.on_added_line(entry.file, entry.line):
            scope.append(entry)
        else:
            dropped.append(f"{entry.file}:{entry.line} scope creep: not an added line")

    validated = ReviewResult(findings=tuple(findings), criteria=tuple(criteria), scope_creep=tuple(scope))
    return Validated(validated, tuple(dropped))


class _Checker:
    def __init__(self, context: ReviewContext) -> None:
        self._added = {
            f.path: frozenset(a.number for a in f.added_lines) for f in context.files if f.status != "removed"
        }
        self._rule_lines = {r.path: len(r.text.splitlines()) for r in context.rules}
        self.criteria = frozenset(f"{r.source}/{c.key}" for r in context.requirements for c in r.criteria)
        self._prose = frozenset(r.source for r in context.requirements if not r.criteria)

    def inferred_problem(self, item: CriterionResult) -> str | None:
        """None when the item is a valid inferred criterion (ADR 0011)."""
        source, _, label = item.criterion.rpartition("/")
        number = _INFERRED.fullmatch(label)
        if source not in self._prose or number is None or int(number[1]) > INFERRED_LIMIT:
            return "no such acceptance criterion"
        if not item.text or not item.text.strip():
            return "inferred criterion needs text"
        if len(item.text) > INFERRED_TEXT_LIMIT:
            return "inferred criterion text is too long"
        return None

    def on_added_line(self, file: str, line: int) -> bool:
        return line in self._added.get(file, frozenset())

    def in_change(self, location: Location) -> bool:
        # A test that proves a criterion may sit on an unchanged line of a changed file.
        return location.file in self._added and location.line >= 1

    def finding_problem(self, finding: Finding) -> str | None:
        if finding.file not in self._added:
            return "file is not part of the change"
        if finding.line_start > finding.line_end:
            return "line range is reversed"
        lines = range(finding.line_start, finding.line_end + 1)
        if not all(self.on_added_line(finding.file, line) for line in lines):
            # GitHub rejects the whole review when one comment is off the diff or spans two hunks. A run of
            # consecutive added lines always sits inside one hunk.
            return "lines are not added by this change"
        if finding.evidence is None:
            return (
                "rule and requirement findings need evidence" if finding.category in _NEEDS_EVIDENCE else None
            )
        if self._evidence_exists(finding.evidence):
            return None
        return f"evidence {finding.evidence} cites nothing bylaw collected"

    def _evidence_exists(self, evidence: str) -> bool:
        if evidence in self.criteria:
            return True
        path, separator, line = evidence.rpartition(":")
        return bool(separator) and line.isdigit() and 1 <= int(line) <= self._rule_lines.get(path, 0)
