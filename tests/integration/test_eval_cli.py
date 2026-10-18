from pathlib import Path

import pytest

from bylaw.cli import main


def _write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


@pytest.fixture
def evalset(tmp_path: Path) -> Path:
    root = tmp_path / "set"
    _write(root / "projects/p/app.py", b"def run():\n    return 1\n")
    _write(
        root / "cases/one/case.toml",
        b'project = "p"\nkind = "bug"\ntitle = "t"\nmessage = "m"\n\n'
        b'[[findings]]\nfile = "app.py"\nlines = [2, 2]\ncategories = ["bug"]\nnote = "wrong value"\n',
    )
    _write(root / "cases/one/head/app.py", b"def run():\n    return 2\n")
    return root


def test_prepare_then_answers_then_score_works_without_a_model(evalset: Path, tmp_path: Path) -> None:
    host, runs, report = tmp_path / "host", tmp_path / "runs", tmp_path / "report.md"
    assert main(["eval", "prepare", "--set", str(evalset), "--out", str(host)]) == 0
    (host / "one.json").write_text(
        '{"findings": [{"file": "app.py", "line_start": 2, "line_end": 2, "category": "bug", '
        '"severity": "high", "message": "returns 2"}], "criteria": [], "scope_creep": []}',
        encoding="utf-8",
    )

    assert main(["eval", "run", "--set", str(evalset), "--out", str(runs), "--answers", str(host)]) == 0
    code = main(
        [
            "eval",
            "score",
            "--set",
            str(evalset),
            "--runs",
            str(runs),
            "--label",
            "host",
            "--output",
            str(report),
        ]
    )

    assert code == 0
    assert "| bug | 1 | 0 | 0 | 100% | 100% |" in report.read_text(encoding="utf-8")


def test_the_no_model_baseline_runs_without_errors(evalset: Path, tmp_path: Path) -> None:
    runs = tmp_path / "runs"

    assert main(["eval", "run", "--set", str(evalset), "--out", str(runs), "--no-model"]) == 0
    assert '"error": null' in (runs / "one.json").read_text(encoding="utf-8")


def test_a_model_run_without_a_key_says_so(
    evalset: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("BYLAW_API_KEY", raising=False)

    code = main(
        ["eval", "run", "--set", str(evalset), "--out", str(tmp_path / "r"), "--provider", "anthropic"]
    )

    assert code == 2
    assert "eval run needs ANTHROPIC_API_KEY" in capsys.readouterr().err


def test_a_model_run_without_a_key_names_both_variables(
    evalset: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("BYLAW_API_KEY", raising=False)

    main(["eval", "run", "--set", str(evalset), "--out", str(tmp_path / "r"), "--provider", "anthropic"])

    assert "ANTHROPIC_API_KEY or BYLAW_API_KEY" in capsys.readouterr().err


def test_a_run_with_failed_cases_exits_1_and_says_how_many(
    evalset: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    empty = tmp_path / "no-answers"
    empty.mkdir()

    code = main(["eval", "run", "--set", str(evalset), "--out", str(tmp_path / "r"), "--answers", str(empty)])

    err = capsys.readouterr().err
    assert code == 1
    assert "reviewing 1 case(s)" in err
    assert "1 failed" in err


def test_a_cost_limit_needs_the_prices(
    evalset: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = main(
        ["eval", "run", "--set", str(evalset), "--out", str(tmp_path / "r"), "--no-model", "--max-cost", "5"]
    )

    assert code == 2
    assert "--max-cost needs --input-price and --output-price" in capsys.readouterr().err


def test_a_snapshot_without_a_token_says_how_to_get_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("GH_TOKEN", raising=False)

    code = main(["eval", "snapshot", "--repo", "octo/app", "--pr", "7", "--id", "x", "--set", str(tmp_path)])

    assert code == 2
    assert "gh auth token" in capsys.readouterr().err
    assert not (tmp_path / "cases").exists()
