"""The committed evaluation set: every label is reachable, and an oracle reviewer scores perfectly."""

from collections import Counter
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

    def review(self, system: str, user: str) -> ReviewResult:
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
            CriterionResult(criterion=key, status=ok[0]) for key, ok in self._case.criteria.items()
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


def test_the_set_has_the_size_and_mix_the_design_asks_for(cases: tuple[Case, ...]) -> None:
    kinds = Counter(case.kind for case in cases)

    assert 40 <= len(cases) <= 60
    assert kinds["clean"] >= 8
    assert all(kinds[k] >= 4 for k in ("security", "bug", "rule", "requirement", "scope"))
    assert {case.project for case in cases} == {
        "go-api",
        "ts-shop",
        "cs-orders",
        "py-users",
        "py-mono",
        "py-ledger",
    }


def test_the_monorepo_cases_need_a_package_rule_or_a_linter_rule_id(
    cases: tuple[Case, ...], contexts: dict[str, ReviewContext]
) -> None:
    mono = [case for case in cases if case.project == "py-mono"]
    cited = {label.evidence for case in mono for label in case.findings}

    assert {"packages/api/AGENTS.md:3", "packages/worker/AGENTS.md:3", "ruff:S608", "ruff:B006"} <= cited
    assert any(case.kind == "clean" for case in mono)
    # Only the package with changed files is read: the worker's rules stay out of an API change.
    api = [rule.path for rule in contexts["py-mono-api-raises"].rules]
    assert "packages/api/AGENTS.md" in api
    assert "packages/worker/AGENTS.md" not in api


def test_every_deterministic_label_is_found_without_a_model(
    cases: tuple[Case, ...], contexts: dict[str, ReviewContext]
) -> None:
    for case in cases:
        for label in (label for label in case.findings if label.deterministic):
            found = contexts[case.id].findings
            assert any(f.file == label.file and f.line_start == label.lines[0] for f in found), case.id


def test_the_ledger_cases_are_held_to_the_accepted_adr_alone(
    cases: tuple[Case, ...], contexts: dict[str, ReviewContext]
) -> None:
    ledger = [case for case in cases if case.project == "py-ledger"]
    accepted = "docs/adr/0002-sqlite-through-the-store-module.md"

    assert {case.kind for case in ledger} == {"rule", "clean"}
    assert any(label.evidence == f"{accepted}:12" for case in ledger for label in case.findings)
    # The superseded JSON decision and the proposed async one would both condemn the clean change.
    assert all([d.path for d in contexts[case.id].decisions] == [accepted] for case in ledger)
    assert all(not contexts[case.id].requirements for case in ledger)
