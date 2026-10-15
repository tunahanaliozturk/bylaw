from bylaw.evaluation.cases import Case, ExpectedCreep, ExpectedFinding, Span
from bylaw.evaluation.run import CaseRun
from bylaw.evaluation.score import score
from bylaw.model import (
    Category,
    CriterionResult,
    CriterionStatus,
    Finding,
    ReviewResult,
    ScopeCreep,
    Severity,
)

SQLI = ExpectedFinding(file="app.py", lines=(10, 10), categories=(Category.SECURITY,), note="sqli")


def _case(case_id: str = "c", kind: str = "security", **labels: object) -> Case:
    return Case.model_validate(
        {"id": case_id, "project": "p", "kind": kind, "title": "t", "message": "m", **labels}
    )


def _found(line: int, category: Category = Category.SECURITY, severity: Severity = Severity.HIGH) -> Finding:
    return Finding(
        file="app.py", line_start=line, line_end=line, category=category, severity=severity, message="x"
    )


def _run(case_id: str = "c", *findings: Finding, **result: object) -> CaseRun:
    return CaseRun(
        case_id=case_id,
        result=ReviewResult.model_validate({"findings": findings, **result}),
        dropped=(),
        model_findings=len(findings),
    )


def _category(result_score, category: Category):  # type: ignore[no-untyped-def]
    return next(c for c in result_score.categories if c.category == category)


def test_a_finding_within_two_lines_and_the_right_category_is_a_hit() -> None:
    result = score([_case(findings=[SQLI])], [_run("c", _found(12))])

    security = _category(result, Category.SECURITY)
    assert (security.true_positives, security.false_positives, security.false_negatives) == (1, 0, 0)
    assert security.precision == security.recall == 1.0


def test_a_wrong_category_is_a_miss_and_a_false_alarm_but_still_located() -> None:
    result = score([_case(findings=[SQLI])], [_run("c", _found(10, Category.BUG))])

    assert _category(result, Category.SECURITY).false_negatives == 1
    assert _category(result, Category.BUG).false_positives == 1
    assert result.located == 1
    assert result.misses == ("c: sqli",)


def test_the_same_defect_reported_twice_is_a_duplicate_not_a_false_alarm() -> None:
    result = score([_case(findings=[SQLI])], [_run("c", _found(10), _found(11))])

    assert _category(result, Category.SECURITY).false_positives == 0
    assert result.duplicates == 1


def test_a_finding_in_an_allowed_span_is_ignored() -> None:
    case = _case(findings=[SQLI], allowed=[Span(file="app.py", lines=(20, 30))])

    result = score([case], [_run("c", _found(10), _found(25, Category.BUG))])

    assert _category(result, Category.BUG).false_positives == 0


def test_a_medium_finding_on_a_clean_case_counts_as_an_inline_false_alarm() -> None:
    cases = [_case("ok", "clean"), _case("noisy", "clean")]
    runs = [_run("ok", _found(3, severity=Severity.LOW)), _run("noisy", _found(3, severity=Severity.MEDIUM))]

    result = score(cases, runs)

    assert (result.clean_cases, result.clean_with_inline) == (2, 1)


def test_criteria_count_as_correct_when_the_status_is_accepted() -> None:
    case = _case(
        kind="requirement", criteria={"spec.md/AC-1": ["partial", "missing"], "spec.md/AC-2": ["met"]}
    )
    run = _run(
        "c",
        criteria=[
            CriterionResult(criterion="spec.md/AC-1", status=CriterionStatus.MISSING),
            CriterionResult(criterion="spec.md/AC-2", status=CriterionStatus.PARTIAL),
        ],
    )

    result = score([case], [run])

    assert (result.criteria_correct, result.criteria_total) == (1, 2)


def test_scope_creep_matches_on_file_and_nearby_line() -> None:
    case = _case(kind="scope", scope_creep=[ExpectedCreep(file="app.py", line=7)])
    run = _run(
        "c",
        scope_creep=[
            ScopeCreep(file="app.py", line=8, message="x"),
            ScopeCreep(file="b.py", line=1, message="y"),
        ],
    )

    result = score([case], [run])

    assert (result.creep_expected, result.creep_found, result.creep_extra) == (1, 1, 1)


def test_a_case_without_a_run_is_an_error_not_a_crash() -> None:
    result = score([_case(findings=[SQLI])], [])

    assert result.errors == ("c: no run",)
    assert _category(result, Category.SECURITY).false_negatives == 1


def test_a_category_nobody_predicted_or_labelled_has_no_precision_or_recall() -> None:
    result = score([_case()], [_run("c")])

    rule = _category(result, Category.RULE)
    assert rule.precision is None
    assert rule.recall is None
