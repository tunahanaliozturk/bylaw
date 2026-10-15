import json
from pathlib import Path

import pytest

from bylaw import cli
from bylaw.engine import ReviewError
from bylaw.model import Category, Finding, ReviewResult, Severity

CONTEXT = {
    "base_sha": "b",
    "head_sha": "h",
    "title": "t",
    "files": [
        {
            "path": "app.py",
            "status": "added",
            "added_lines": [{"number": 1, "text": "x = eval(input())"}],
            "patch": "@@ -0,0 +1 @@\n+x = eval(input())\n",
        }
    ],
    "rules": [],
    "requirements": [],
    "findings": [],
    "notes": [],
}
HIGH = Finding(
    file="app.py",
    line_start=1,
    line_end=1,
    category=Category.SECURITY,
    severity=Severity.HIGH,
    message="eval of input",
)


class FakeReviewer:
    def __init__(self, result: ReviewResult | None = None, error: str | None = None) -> None:
        self.result = result or ReviewResult()
        self.error = error
        self.calls = 0

    def review(self, system: str, user: str) -> ReviewResult:
        self.calls += 1
        if self.error:
            raise ReviewError(self.error)
        return self.result


@pytest.fixture
def context_file(tmp_path: Path) -> Path:
    path = tmp_path / "context.json"
    path.write_text(json.dumps(CONTEXT), encoding="utf-8")
    return path


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "BYLAW_API_KEY",
        "ANTHROPIC_API_KEY",
        "OPENAI_API_KEY",
        "GITHUB_EVENT_NAME",
        "GITHUB_EVENT_PATH",
    ):
        monkeypatch.delenv(name, raising=False)


def _use(monkeypatch: pytest.MonkeyPatch, reviewer: FakeReviewer) -> None:
    monkeypatch.setattr(cli, "make_reviewer", lambda *_args: reviewer)


def test_without_a_key_only_the_deterministic_checks_run(
    context_file: Path, monkeypatch: pytest.MonkeyPatch, capsysbinary: pytest.CaptureFixture[bytes]
) -> None:
    reviewer = FakeReviewer(ReviewResult(findings=(HIGH,)))
    _use(monkeypatch, reviewer)

    code = cli.main(["review", "--context", str(context_file)])

    output = json.loads(capsysbinary.readouterr().out)
    assert (code, reviewer.calls, output["result"]["findings"]) == (0, 0, [])


def test_with_a_key_the_model_findings_are_validated_and_returned(
    context_file: Path, monkeypatch: pytest.MonkeyPatch, capsysbinary: pytest.CaptureFixture[bytes]
) -> None:
    monkeypatch.setenv("BYLAW_API_KEY", "k")
    _use(monkeypatch, FakeReviewer(ReviewResult(findings=(HIGH,))))

    code = cli.main(["review", "--context", str(context_file)])

    output = json.loads(capsysbinary.readouterr().out)
    assert code == 0
    assert [f["message"] for f in output["result"]["findings"]] == ["eval of input"]


def test_fail_on_turns_a_remaining_finding_into_exit_code_one(
    context_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("BYLAW_API_KEY", "k")
    _use(monkeypatch, FakeReviewer(ReviewResult(findings=(HIGH,))))

    assert cli.main(["review", "--context", str(context_file), "--fail-on", "high"]) == 1
    assert cli.main(["review", "--context", str(context_file), "--fail-on", "critical"]) == 0


def test_a_model_failure_leaves_a_note_and_still_succeeds(
    context_file: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsysbinary: pytest.CaptureFixture[bytes],
) -> None:
    monkeypatch.setenv("BYLAW_API_KEY", "k")
    _use(monkeypatch, FakeReviewer(error="the model declined to review this change (cyber)"))

    code = cli.main(["review", "--context", str(context_file)])

    captured = capsysbinary.readouterr()
    assert code == 0
    assert b"The model review did not run: the model declined to review this change (cyber)." in captured.err


def test_a_fork_pull_request_without_secrets_exits_quietly(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    event = tmp_path / "event.json"
    event.write_text(
        json.dumps(
            {
                "pull_request": {
                    "head": {"repo": {"full_name": "fork/app"}},
                    "base": {"repo": {"full_name": "octo/app"}},
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("GITHUB_EVENT_NAME", "pull_request")
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(event))

    code = cli.main(["review", "--pr", "5", "--repo", "octo/app", "--post"])

    assert code == 0
    assert "::notice title=bylaw::" in capsys.readouterr().out


@pytest.mark.parametrize(
    ("actor", "head"),
    [("dependabot[bot]", {"repo": {"full_name": "octo/app"}}), ("someone", {"repo": None})],
)
def test_pull_requests_without_secrets_exit_quietly(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    actor: str,
    head: dict[str, object],
) -> None:
    event = tmp_path / "event.json"
    event.write_text(
        json.dumps({"pull_request": {"head": head, "base": {"repo": {"full_name": "octo/app"}}}}),
        encoding="utf-8",
    )
    monkeypatch.setenv("GITHUB_EVENT_NAME", "pull_request")
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(event))
    monkeypatch.setenv("GITHUB_ACTOR", actor)

    assert cli.main(["review", "--pr", "5", "--repo", "octo/app", "--post"]) == 0
    assert "::notice title=bylaw::" in capsys.readouterr().out


def test_text_from_a_model_cannot_start_a_workflow_command(
    context_file: Path, monkeypatch: pytest.MonkeyPatch, capsysbinary: pytest.CaptureFixture[bytes]
) -> None:
    planted = Finding(
        file="x.py\n::error::planted",
        line_start=1,
        line_end=1,
        category=Category.BUG,
        severity=Severity.HIGH,
        message="m",
    )
    monkeypatch.setenv("BYLAW_API_KEY", "k")
    _use(monkeypatch, FakeReviewer(ReviewResult(findings=(planted,))))

    cli.main(["review", "--context", str(context_file)])

    lines = capsysbinary.readouterr().err.decode("utf-8").splitlines()
    assert not any(line.startswith("::") for line in lines)


def test_the_effort_is_left_to_the_engine_unless_given(
    context_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[object] = []

    def capture(*args: object) -> FakeReviewer:
        seen.append(args[2])
        return FakeReviewer()

    monkeypatch.setenv("BYLAW_API_KEY", "k")
    monkeypatch.setattr(cli, "make_reviewer", capture)

    cli.main(["review", "--context", str(context_file), "--provider", "openai", "--model", "m"])

    assert seen == [None]
