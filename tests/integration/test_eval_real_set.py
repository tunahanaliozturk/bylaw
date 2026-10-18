"""The committed real set: every case keeps its licence, replays offline, and its labels are reachable."""

import socket
from collections import Counter
from pathlib import Path

import pytest

from bylaw.evaluation.cases import Case, build_case_context, load_cases
from bylaw.evaluation.run import run_case
from bylaw.evaluation.score import score
from bylaw.evaluation.snapshot import LICENCES
from bylaw.model import ReviewContext
from tests.integration.test_eval_set import Oracle

ROOT = Path(__file__).resolve().parents[2] / "eval" / "real"


@pytest.fixture(scope="module")
def cases() -> tuple[Case, ...]:
    return load_cases(ROOT)


@pytest.fixture(scope="module")
def contexts(cases: tuple[Case, ...], tmp_path_factory: pytest.TempPathFactory) -> dict[str, ReviewContext]:
    def no_network(*_: object, **__: object) -> None:
        raise AssertionError("a real case opened a network connection on replay")

    work = tmp_path_factory.mktemp("real")
    # Every case is built offline: ADR 0015 promises a run never reads GitHub or a tracker.
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(socket.socket, "connect", no_network)
        patch.setattr(socket, "getaddrinfo", no_network)
        return {case.id: build_case_context(ROOT, case, work) for case in cases}


def test_an_oracle_reviewer_scores_perfectly_on_the_real_set(
    cases: tuple[Case, ...], contexts: dict[str, ReviewContext]
) -> None:
    runs = [run_case(contexts[case.id], case.id, Oracle(case)) for case in cases]
    result = score(cases, runs)

    assert {r.case_id: r.dropped for r in runs if r.dropped} == {}
    assert result.misses == ()
    assert result.false_alarms == ()
    assert result.criteria_correct == result.criteria_total


def test_every_real_case_keeps_its_licence_notice(cases: tuple[Case, ...]) -> None:
    for case in cases:
        assert case.pull_request is not None, case.id
        assert case.pull_request.licence in LICENCES, case.id
        notices = [p.name for p in (ROOT / "cases" / case.id).iterdir() if p.is_file()]
        assert any(n.upper().startswith(("LICENSE", "LICENCE", "COPYING")) for n in notices), case.id


def test_the_real_set_has_the_size_and_spread_the_rules_ask_for(cases: tuple[Case, ...]) -> None:
    projects = Counter(case.pull_request.repo for case in cases if case.pull_request)

    assert 20 <= len(cases) <= 30
    assert len(projects) >= 6
    assert max(projects.values()) <= 5
    assert all(case.kind != "clean" for case in cases)
    assert all(case.pull_request and case.pull_request.evidence for case in cases)
