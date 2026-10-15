import json
from importlib.metadata import version
from pathlib import Path

import pytest

from bylaw.cli import main


def test_version_flag_prints_the_installed_version(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exit_info:
        main(["--version"])

    assert exit_info.value.code == 0
    assert capsys.readouterr().out.strip() == f"bylaw {version('bylaw')}"


def test_pr_mode_without_a_token_fails_with_a_clear_message(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("GH_TOKEN", raising=False)

    code = main(["context", "--pr", "5", "--repo", "octo/app"])

    assert code == 2
    assert capsys.readouterr().err.strip() == "bylaw: GITHUB_TOKEN or GH_TOKEN is required with --pr"


def test_pr_mode_without_a_repository_fails_with_a_clear_message(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("GITHUB_TOKEN", "t")
    monkeypatch.delenv("GITHUB_REPOSITORY", raising=False)

    code = main(["context", "--pr", "5"])

    assert code == 2
    assert "--repo or GITHUB_REPOSITORY" in capsys.readouterr().err


def test_validate_reports_what_it_dropped(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    context = tmp_path / "context.json"
    result = tmp_path / "result.json"
    context.write_text(
        '{"base_sha": "b", "head_sha": "h", "title": "t", "files": [], "rules": [], '
        '"requirements": [], "findings": [], "notes": []}',
        encoding="utf-8",
    )
    result.write_text(
        '{"findings": [{"file": "x.py", "line_start": 1, "line_end": 1, "category": "bug", '
        '"severity": "high", "message": "m"}]}',
        encoding="utf-8",
    )

    code = main(["validate", "--context", str(context), "--result", str(result)])

    output = json.loads(capsys.readouterr().out)
    assert code == 0
    assert output["result"]["findings"] == []
    assert output["dropped"] == ["x.py:1 bug: file is not part of the change"]
