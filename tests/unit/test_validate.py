from bylaw.model import (
    AddedLine,
    Category,
    ChangedFile,
    Criterion,
    CriterionResult,
    CriterionStatus,
    Finding,
    Location,
    Requirement,
    ReviewContext,
    ReviewResult,
    RuleKind,
    RuleSource,
    ScopeCreep,
    Severity,
)
from bylaw.validate import validate

CONTEXT = ReviewContext(
    base_sha="b",
    head_sha="h",
    title="t",
    files=(
        ChangedFile(
            path="app.py",
            status="modified",
            added_lines=tuple(AddedLine(number=n, text=f"line {n}") for n in (3, 4, 5)),
        ),
        ChangedFile(path="old.py", status="removed"),
    ),
    rules=(RuleSource(path="CONTRIBUTING.md", kind=RuleKind.PROSE, text="one\ntwo\nthree\n"),),
    requirements=(
        Requirement(
            source="issue#1", title="Login", text="", criteria=(Criterion(key="AC-1", text="Sign in"),)
        ),
    ),
    findings=(),
    notes=(),
)


def _finding(
    file: str = "app.py",
    start: int = 3,
    end: int = 3,
    category: Category = Category.SECURITY,
    evidence: str | None = None,
) -> Finding:
    return Finding(
        file=file,
        line_start=start,
        line_end=end,
        category=category,
        severity=Severity.HIGH,
        message="m",
        evidence=evidence,
    )


def _dropped(*findings: Finding) -> tuple[str, ...]:
    return validate(CONTEXT, ReviewResult(findings=findings)).dropped


def test_a_backed_finding_survives() -> None:
    kept = validate(CONTEXT, ReviewResult(findings=(_finding(evidence="CONTRIBUTING.md:2"),)))

    assert len(kept.result.findings) == 1
    assert kept.dropped == ()


def test_findings_outside_the_added_lines_are_dropped() -> None:
    assert _dropped(_finding(file="other.py")) == ("other.py:3 security: file is not part of the change",)
    assert _dropped(_finding(file="old.py")) == ("old.py:3 security: file is not part of the change",)
    assert _dropped(_finding(start=2, end=3)) == ("app.py:2 security: lines are not added by this change",)
    assert _dropped(_finding(start=5, end=4)) == ("app.py:5 security: line range is reversed",)


def test_rule_and_requirement_findings_need_evidence() -> None:
    assert _dropped(_finding(category=Category.RULE)) == (
        "app.py:3 rule: rule and requirement findings need evidence",
    )
    assert _dropped(_finding(category=Category.BUG)) == ()


def test_invented_citations_are_dropped() -> None:
    assert _dropped(_finding(evidence="CONTRIBUTING.md:9")) == (
        "app.py:3 security: evidence CONTRIBUTING.md:9 cites nothing bylaw collected",
    )
    assert _dropped(_finding(evidence="SECURITY.md:1")) != ()
    assert _dropped(_finding(category=Category.REQUIREMENT, evidence="issue#1/AC-1")) == ()
    assert _dropped(_finding(category=Category.REQUIREMENT, evidence="issue#1/AC-7")) != ()


def test_a_second_finding_on_the_same_lines_and_category_is_dropped() -> None:
    assert _dropped(_finding(), _finding()) == (
        "app.py:3 security: duplicates another finding on the same lines",
    )


def test_criteria_results_keep_only_known_criteria_and_changed_locations() -> None:
    result = ReviewResult(
        criteria=(
            CriterionResult(
                criterion="issue#1/AC-1",
                status=CriterionStatus.MET,
                code=(Location(file="app.py", line=4), Location(file="elsewhere.py", line=1)),
            ),
            CriterionResult(criterion="issue#1/AC-9", status=CriterionStatus.MET),
            CriterionResult(criterion="issue#1/AC-1", status=CriterionStatus.MISSING),
        )
    )

    validated = validate(CONTEXT, result)

    assert [(c.criterion, c.code) for c in validated.result.criteria] == [
        ("issue#1/AC-1", (Location(file="app.py", line=4),))
    ]
    assert validated.dropped == (
        "issue#1/AC-1: 1 location(s) outside the change",
        "issue#1/AC-9: no such acceptance criterion",
        "issue#1/AC-1: duplicate criterion result",
    )


def test_scope_creep_must_point_at_an_added_line() -> None:
    result = ReviewResult(
        scope_creep=(
            ScopeCreep(file="app.py", line=5, message="new endpoint"),
            ScopeCreep(file="app.py", line=1, message="x"),
        )
    )

    validated = validate(CONTEXT, result)

    assert [s.line for s in validated.result.scope_creep] == [5]
    assert validated.dropped == ("app.py:1 scope creep: not an added line",)
