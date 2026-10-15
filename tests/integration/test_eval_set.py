"""The committed evaluation set: every label must be reachable, and a reviewer that knows the labels scores perfectly."""

from pathlib import Path

import pytest

from bylaw.evaluation.cases import Case, build_case_context, load_cases
from bylaw.evaluation.run import run_case
from bylaw.evaluation.score import score
from bylaw.model import CriterionResult, Finding, ReviewContext, ReviewResult, ScopeCreep, Severity

ROOT = Path(__file__).resolve().parents[2] / "eval"


class Oracle:
    """Answers with exactly the labels; whatever validate drops or the scorer misses is a labelling error."""

    def __init__(self, case: Case) -> None:
        self._case = case

    def review(self, system: str, user: str) -> ReviewResult:  # noqa: ARG002
        findings = tuple(
            Finding(
                file=label.file,
                line_start=label.lines[0],
                line_end=label.lines[1],
                category=label.categories[0],
                severity=Severity.HIGH,
                message=label.note,
                evidence=label.evidence,
            )
            for label in self._case.findings
            if not label.deterministic
        )
        criteria = tuple(
            CriterionResult(criterion=key, status=accepted[0]) for key, accepted in self._case.criteria.items()
        )
        creep = tuple(ScopeCreep(file=c.file, line=c.line, message="creep") for c in self._case.scope_creep)
        return ReviewResult(findings=findings, criteria=criteria, scope_creep=creep)


@pytest.fixture(scope="module")
def cases() -> tuple[Case, ...]:
    return load_cases(ROOT)


@pytest.fixture(scope="module")
def contexts(cases: tuple[Case, ...], tmp_path_factory: pytest.TempPathFactory) -> dict[str, ReviewContext]:
    # Built once: on Windows each case costs a couple of seconds of git process start-up.
    work = tmp_path_factory.mktemp("eval")
    return {case.id: build_case_context(ROOT, case, work) for case in cases}


def test_an_oracle_reviewer_scores_perfectly(
    cases: tuple[Case, ...], contexts: dict[str, ReviewContext]
) -> None:
    runs = [run_case(contexts[case.id], case.id, Oracle(case)) for case in cases]
    result = score(cases, runs)

    assert {r.case_id: r.dropped for r in runs if r.dropped} == {}
    assert result.misses == ()
    assert result.false_alarms == ()
    assert result.duplicates == 0
    assert result.criteria_correct == result.criteria_total
    assert (result.creep_found, result.creep_extra) == (result.creep_expected, 0)
    assert result.clean_with_inline == 0
