from pathlib import Path

import pytest

from bylaw import cli
from bylaw.cli import main
from bylaw.evaluation.run import NoModel


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


def test_a_local_model_run_needs_no_key_and_names_the_provider_and_model(
    evalset: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    seen: list[tuple[object, ...]] = []

    def local(*args: object) -> NoModel:
        seen.append(args)
        return NoModel()

    monkeypatch.delenv("BYLAW_API_KEY", raising=False)
    monkeypatch.setattr(cli, "make_reviewer", local)
    runs = tmp_path / "r"

    code = main(
        [
            "eval",
            "run",
            "--set",
            str(evalset),
            "--out",
            str(runs),
            "--provider",
            "openai-compatible",
            "--base-url",
            "http://localhost:11434/v1",
            "--model",
            "qwen3:4b",
        ]
    )

    assert code == 0
    assert seen == [("openai-compatible", "qwen3:4b", None, None, "http://localhost:11434/v1")]
    assert "with openai-compatible:qwen3:4b:default effort" in capsys.readouterr().err
    assert '"reviewer": "openai-compatible:qwen3:4b:default effort"' in (runs / "one.json").read_text("utf-8")


def test_a_model_run_without_an_openai_key_names_its_variable(
    evalset: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("BYLAW_API_KEY", raising=False)

    code = main(["eval", "run", "--set", str(evalset), "--out", str(tmp_path / "r"), "--provider", "openai"])

    assert code == 2
    assert "OPENAI_API_KEY or BYLAW_API_KEY" in capsys.readouterr().err


@pytest.mark.parametrize(
    "target",
    [
        ("bedrock", None),
        ("vertex", "claude-sonnet-5-5"),
        ("foundry", None),
        ("azure-openai", "review-deployment"),
    ],
)
def test_a_cloud_provider_run_needs_no_bylaw_key_and_keeps_the_spending_limit(
    evalset: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    target: tuple[str, str | None],
) -> None:
    provider, model = target
    monkeypatch.delenv("BYLAW_API_KEY", raising=False)
    monkeypatch.setattr(cli, "make_reviewer", lambda *_args: NoModel())
    runs = tmp_path / "r"
    flags = ["--model", model] if model else []

    code = main(
        [
            "eval",
            "run",
            "--set",
            str(evalset),
            "--out",
            str(runs),
            "--provider",
            provider,
            *flags,
            "--effort",
            "medium",
            "--max-cost",
            "5",
            "--input-price",
            "5",
            "--output-price",
            "25",
        ]
    )

    identity = f"{provider}:{model or 'default model'}:medium"
    assert code == 0
    assert f"with {identity}" in capsys.readouterr().err
    assert f'"reviewer": "{identity}"' in (runs / "one.json").read_text("utf-8")
