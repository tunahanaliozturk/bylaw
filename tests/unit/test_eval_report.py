from bylaw.evaluation.cases import Case, ExpectedFinding
from bylaw.evaluation.report import render
from bylaw.evaluation.run import CaseRun
from bylaw.evaluation.score import score
from bylaw.model import Category, Finding, ReviewResult, Severity


def test_the_report_names_the_label_metrics_and_cost() -> None:
    case = Case(
        id="c",
        project="p",
        kind="security",
        title="t",
        message="m",
        findings=(ExpectedFinding(file="a.py", lines=(1, 1), categories=(Category.SECURITY,), note="sqli"),),
    )
    found = Finding(
        file="a.py", line_start=1, line_end=1, category=Category.SECURITY, severity=Severity.HIGH, message="x"
    )
    run = CaseRun(
        case_id="c",
        result=ReviewResult(findings=(found,)),
        dropped=(),
        model_findings=1,
        seconds=4.0,
        input_tokens=2_000_000,
        output_tokens=1_000_000,
    )

    text = render(score([case], [run]), "test-model 2026-10-15", input_price=1.0, output_price=10.0)

    assert text.startswith("# Evaluation: test-model 2026-10-15")
    assert "| security | 1 | 0 | 0 | 100% | 100% |" in text
    assert "$12.00 per pull request" in text
    assert "4.0 s median" in text
    assert "Other remarks on planted code, not scored: 0" in text
    assert "over 1 reviewed cases" in text
