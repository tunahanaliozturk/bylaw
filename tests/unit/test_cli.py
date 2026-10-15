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


def test_schema_prints_the_review_result_schema(capsysbinary: pytest.CaptureFixture[bytes]) -> None:
    code = main(["schema"])

    schema = json.loads(capsysbinary.readouterr().out)
    assert code == 0
    assert set(schema["required"]) == {"findings", "criteria", "scope_creep"}


def test_a_result_that_breaks_the_schema_is_a_clear_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    context = tmp_path / "context.json"
    result = tmp_path / "result.json"
    context.write_text(
        '{"base_sha": "b", "head_sha": "h", "title": "t", "files": [], "rules": [], '
        '"requirements": [], "findings": [], "notes": []}',
        encoding="utf-8",
    )
    result.write_text('{"findings": [{"file": "a.py"}]}', encoding="utf-8")

    code = main(["validate", "--context", str(context), "--result", str(result)])

    error = capsys.readouterr().err
    assert code == 2
    assert error.startswith("bylaw: ")
    assert "Traceback" not in error


_EMPTY_CONTEXT = (
    '{"base_sha": "b", "head_sha": "h", "title": "t", "files": [], "rules": [], '
    '"requirements": [], "findings": [], "notes": []}'
)


@pytest.mark.parametrize("encoding", ["utf-8-sig", "utf-16"])
def test_a_context_file_a_windows_shell_saved_with_a_byte_order_mark_still_reads(
    tmp_path: Path, encoding: str
) -> None:
    # PowerShell 7 writes `>` as UTF-8 with a BOM, Windows PowerShell 5.1 as UTF-16.
    context = tmp_path / "context.json"
    context.write_text(_EMPTY_CONTEXT, encoding=encoding)

    assert main(["validate", "--context", str(context)]) == 0


def test_prompt_writes_the_whole_brief_to_the_output_file(
    tmp_path: Path, capsysbinary: pytest.CaptureFixture[bytes]
) -> None:
    context = tmp_path / "context.json"
    brief = tmp_path / "brief.txt"
    context.write_text(_EMPTY_CONTEXT, encoding="utf-8")

    code = main(["prompt", "--context", str(context), "--output", str(brief)])

    assert code == 0
    assert capsysbinary.readouterr().out == b""
    assert "\n---\n" in brief.read_bytes().decode("utf-8")


def test_prompt_names_the_files_left_out_for_size(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    context = json.loads(_EMPTY_CONTEXT)
    context["files"] = [{"path": "huge.py", "status": "added", "patch": "@@ -0,0 +1 @@\n" + "+x\n" * 450_000}]
    path = tmp_path / "context.json"
    path.write_text(json.dumps(context), encoding="utf-8")

    code = main(["prompt", "--context", str(path), "--output", str(tmp_path / "brief.txt")])

    assert code == 0
    assert "bylaw: Left out of the review for size: huge.py." in capsys.readouterr().err


def test_the_schema_asks_for_criterion_text(capsysbinary: pytest.CaptureFixture[bytes]) -> None:
    main(["schema"])

    schema = json.loads(capsysbinary.readouterr().out)
    criterion = schema["$defs"]["OutCriterion"]
    assert "text" in criterion["required"]
