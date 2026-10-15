from pathlib import Path

import pytest

from bylaw.engine import ReviewError
from bylaw.evaluation.cases import Case, load_cases
from bylaw.evaluation.run import AnswerReviewer, prepare, run_all
from bylaw.model import Category, Finding, ReviewResult, Severity


def _write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


@pytest.fixture
def root(tmp_path: Path) -> Path:
    _write(tmp_path / "projects/p/app.py", b"def run():\n    return 1\n")
    for name in ("a", "b"):
        _write(
            tmp_path / f"cases/{name}/case.toml",
            b'project = "p"\nkind = "clean"\ntitle = "t"\nmessage = "m"\n',
        )
        _write(tmp_path / f"cases/{name}/head/app.py", b"def run():\n    return 2\n")
    return tmp_path


class Counting:
    def __init__(self, fail_on: str = "") -> None:
        self.calls: list[str] = []
        self.fail_on = fail_on

    def maker(self, case: Case) -> "Counting.One":
        return Counting.One(self, case.id)

    class One:
        def __init__(self, owner: "Counting", case_id: str) -> None:
            self.owner, self.case_id = owner, case_id

        def review(self, system: str, user: str) -> ReviewResult:
            self.owner.calls.append(self.case_id)
            if self.case_id == self.owner.fail_on:
                raise ReviewError("overloaded")
            off_change = Finding(
                file="other.py",
                line_start=1,
                line_end=1,
                category=Category.BUG,
                severity=Severity.HIGH,
                message="invented",
            )
            return ReviewResult(findings=(off_change,))


def test_each_case_is_reviewed_validated_and_saved(root: Path, tmp_path: Path) -> None:
    reviewer = Counting()

    runs = run_all(root, load_cases(root), reviewer.maker, tmp_path / "out", tmp_path / "work")

    assert reviewer.calls == ["a", "b"]
    assert [r.model_findings for r in runs] == [1, 1]
    assert runs[0].dropped == ("other.py:1 bug: file is not part of the change",)
    assert runs[0].result.findings == ()
    assert (tmp_path / "out/a.json").is_file()


def test_a_rerun_reuses_saved_results_and_retries_only_failures(root: Path, tmp_path: Path) -> None:
    first = Counting(fail_on="b")
    runs = run_all(root, load_cases(root), first.maker, tmp_path / "out", tmp_path / "w1")
    assert runs[1].error == "overloaded"

    second = Counting()
    run_all(root, load_cases(root), second.maker, tmp_path / "out", tmp_path / "w2")

    assert second.calls == ["b"]


def test_host_answers_are_replayed_and_a_missing_answer_is_an_error(root: Path, tmp_path: Path) -> None:
    out = tmp_path / "host"
    prepare(root, load_cases(root), out, tmp_path / "work")
    assert (out / "a.brief.txt").read_text(encoding="utf-8").count("\n---\n") >= 1
    (out / "a.json").write_text('{"findings": [], "criteria": [], "scope_creep": []}', encoding="utf-8")

    assert AnswerReviewer(out / "a.json").review("s", "u") == ReviewResult()
    with pytest.raises(ReviewError, match="no answer"):
        AnswerReviewer(out / "b.json").review("s", "u")
