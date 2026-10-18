from bylaw.evaluation.cases import FIRST_PASS, Case, ExpectedFinding, Snapshot
from bylaw.evaluation.report import report
from bylaw.evaluation.run import CaseRun
from bylaw.model import Category, Finding, ReviewResult, Severity

PULL = Snapshot(
    repo="octo/app", number=7, url="u", licence="MIT", base_sha="b", head_sha="h", title="Cap retries"
)


def _case(case_id: str, category: Category, **real: object) -> Case:
    label = ExpectedFinding(file="a.py", lines=(1, 1), categories=(category,), note=f"{case_id} defect")
    where: dict[str, object] = {"pull_request": PULL, **real} if real else {"project": "p"}
    return Case.model_validate(
        {"id": case_id, "kind": category.value, "title": "t", "message": "m", "findings": (label,), **where}
    )


def _hit(case_id: str, category: Category) -> CaseRun:
    found = Finding(
        file="a.py", line_start=1, line_end=1, category=category, severity=Severity.HIGH, message="x"
    )
    return CaseRun(case_id=case_id, result=ReviewResult(findings=(found,)), dropped=(), model_findings=1)


def test_the_report_names_the_label_metrics_and_cost() -> None:
    run = _hit("c", Category.SECURITY).model_copy(
        update={"seconds": 4.0, "input_tokens": 2_000_000, "output_tokens": 1_000_000}
    )

    text = report(
        [_case("c", Category.SECURITY)], [run], "test-model 2026-10-15", input_price=1.0, output_price=10.0
    )

    assert text.startswith("# Evaluation: test-model 2026-10-15")
    assert "| security | 1 | 0 | 0 | 100% | 100% |" in text
    assert "$12.00 per pull request" in text
    assert "4.0 s median" in text
    assert "Other remarks on planted code, not scored: 0" in text
    assert "over 1 reviewed cases" in text
    assert "Real pull requests" not in text


def test_real_cases_with_a_first_pass_only_are_provisional_and_kept_apart() -> None:
    cases = [_case("planted", Category.SECURITY), _case("real", Category.BUG, labellers=(FIRST_PASS,))]

    text = report(cases, [_hit("planted", Category.SECURITY)], "m")

    planted, _, real = text.partition("## Real pull requests: provisional labels")
    assert "| bug | 0 | 0 | 0 | n/a | n/a |" in planted
    assert "| bug | 0 | 0 | 1 | n/a | 0% |" in real
    assert "| security | 0 | 0 | 0 |" in real
    assert "1 cases, labelled by fewer than two people" in real
    assert "- real: real defect" in real


def test_real_cases_two_people_labelled_get_their_own_section() -> None:
    cases = [_case("real", Category.BUG, labellers=("ada", "grace"))]

    text = report(cases, [_hit("real", Category.BUG)], "m")

    assert "## Real pull requests\n" in text
    assert "provisional" not in text
    assert "| bug | 1 | 0 | 0 | 100% | 100% |" in text.partition("## Real pull requests")[2]
    # Only real cases: no planted table above them.
    assert "| Category |" not in text.partition("## Real pull requests")[0]
