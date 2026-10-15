"""Drops what the review context cannot back up. Runs on every result, whoever produced it."""

from dataclasses import dataclass

from bylaw.model import Category, CriterionResult, Finding, Location, ReviewContext, ReviewResult, ScopeCreep

_NEEDS_EVIDENCE = frozenset({Category.RULE, Category.REQUIREMENT})


@dataclass(frozen=True, slots=True)
class Validated:
    result: ReviewResult
    dropped: tuple[str, ...]


def validate(context: ReviewContext, result: ReviewResult) -> Validated:
    checker = _Checker(context)
    dropped: list[str] = []

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
            dropped.append(f"{item.criterion}: no such acceptance criterion")
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
        if not (
            self.on_added_line(finding.file, finding.line_start)
            and self.on_added_line(finding.file, finding.line_end)
        ):
            # GitHub rejects the whole review when one comment is off the diff.
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
