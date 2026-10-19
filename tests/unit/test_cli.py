import json
import sys
from importlib.metadata import version
from pathlib import Path

import httpx
import pytest
import respx

from bylaw import cli, pull_review
from bylaw.cli import main
from bylaw.model import ReviewContext
from bylaw.source import SourceError


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


def test_a_dry_run_previews_with_the_settings_in_the_context(
    tmp_path: Path, capsysbinary: pytest.CaptureFixture[bytes]
) -> None:
    context = json.loads(_EMPTY_CONTEXT)
    context["files"] = [{"path": "a.py", "status": "added", "added_lines": [{"number": 1, "text": "x = 1"}]}]
    context["max_comments"] = 0
    result = {
        "findings": [
            {
                "file": "a.py",
                "line_start": 1,
                "line_end": 1,
                "category": "bug",
                "severity": "high",
                "message": "m",
            }
        ]
    }
    (tmp_path / "context.json").write_text(json.dumps(context), encoding="utf-8")
    (tmp_path / "result.json").write_text(json.dumps(result), encoding="utf-8")

    code = main(
        [
            "post",
            "--context",
            str(tmp_path / "context.json"),
            "--result",
            str(tmp_path / "result.json"),
            "--dry-run",
        ]
    )

    preview = capsysbinary.readouterr().out.decode("utf-8")
    assert code == 0
    assert "0 new inline comments" in preview


def test_a_context_with_settings_out_of_range_is_a_clear_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    context = json.loads(_EMPTY_CONTEXT)
    context["max_comments"] = 99
    (tmp_path / "context.json").write_text(json.dumps(context), encoding="utf-8")

    code = main(["post", "--context", str(tmp_path / "context.json"), "--dry-run"])

    assert code == 2
    assert capsys.readouterr().err.startswith("bylaw: ")


def test_bylaw_mcp_without_the_mcp_extra_says_how_to_install_it(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    for name in [n for n in sys.modules if n.partition(".")[0] in {"mcp", "mcp_types"}]:
        monkeypatch.setitem(sys.modules, name, None)
    monkeypatch.delitem(sys.modules, "bylaw.mcp_server", raising=False)

    code = main(["mcp"])

    assert code == 2
    assert "bylaw[mcp]" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("repo_arg", "pinned"),
    [(None, False), ("Acme/App", False), ("attacker/x", True)],
    ids=["own repository", "own repository, other case", "another repository"],
)
def test_context_for_another_repository_sends_tracker_tokens_only_to_pinned_sites(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, repo_arg: str | None, pinned: bool
) -> None:
    # An agent running the skill picks --repo; the Action reviews its own GITHUB_REPOSITORY.
    seen: list[bool] = []

    def build(_source: object, *_args: object, operator_sites: bool = False, **_kw: object) -> object:
        seen.append(operator_sites)
        return ReviewContext.model_validate_json(_EMPTY_CONTEXT)

    monkeypatch.setattr(cli, "build_context", build)
    monkeypatch.setenv("GITHUB_TOKEN", "t")
    monkeypatch.setenv("GITHUB_REPOSITORY", "acme/app")
    repo = ["--repo", repo_arg] if repo_arg else []

    code = main(["context", "--pr", "1", *repo, "--output", str(tmp_path / "context.json")])

    assert code == 0
    assert seen == [pinned]


@pytest.mark.parametrize(
    ("repo_arg", "pinned"),
    [(None, False), ("Acme/App", False), ("attacker/x", True)],
    ids=["own repository", "own repository, other case", "another repository"],
)
def test_review_of_another_repository_sends_tracker_tokens_only_to_pinned_sites(
    monkeypatch: pytest.MonkeyPatch, repo_arg: str | None, pinned: bool
) -> None:
    # HRD-37: the same rule as `bylaw context`, through the real review flow up to the context.
    seen: list[bool] = []

    class Source:
        def __init__(self, *_args: object) -> None: ...

        def read_base(self, _path: str) -> str | None:
            return None

    def build(_source: object, *_args: object, operator_sites: bool = False, **_kw: object) -> object:
        seen.append(operator_sites)
        raise SourceError("stop after the context")

    monkeypatch.setattr(pull_review, "GitHubSource", Source)
    monkeypatch.setattr(pull_review, "build_context", build)
    monkeypatch.setenv("GITHUB_TOKEN", "t")
    monkeypatch.setenv("GITHUB_REPOSITORY", "acme/app")
    monkeypatch.delenv("GITHUB_EVENT_NAME", raising=False)
    repo = ["--repo", repo_arg] if repo_arg else []

    code = main(["review", "--pr", "1", *repo])

    assert code == 2
    assert seen == [pinned]


def test_bylaw_mcp_with_a_root_that_does_not_exist_is_a_clear_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = main(["mcp", "--root", str(tmp_path / "missing")])

    assert code == 2
    assert "not a directory" in capsys.readouterr().err


@respx.mock
def test_with_the_workflow_token_only_github_actions_writes_bylaws_summary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The Action sets BYLAW_BOT_LOGIN when it posts with the workflow token, so a bot a pull request's
    # author can steer, such as a review bot quoting the pull request, cannot plant a summary.
    monkeypatch.setenv("BYLAW_BOT_LOGIN", "github-actions[bot]")
    comments = [
        {"id": 1, "body": "<!-- bylaw:summary --> x", "user": {"type": "Bot", "login": "copilot[bot]"}},
        {
            "id": 2,
            "body": "<!-- bylaw:summary --> y",
            "user": {"type": "Bot", "login": "github-actions[bot]"},
        },
    ]
    respx.get(url__startswith="https://api.github.com/repos/octo/app/issues/5/comments").mock(
        return_value=httpx.Response(200, json=comments)
    )

    with cli.github_client("t", "https://api.github.com") as client:
        summary = client.summary_comment("octo/app", 5)

    assert summary is not None
    assert summary.id == 2


def test_the_action_names_its_bot_only_when_it_posts_with_the_workflow_token() -> None:
    action = (Path(__file__).resolve().parents[2] / "action.yml").read_text(encoding="utf-8")
    line = "BYLAW_BOT_LOGIN: ${{ inputs.github-token == github.token && 'github-actions[bot]' || '' }}"

    assert action.count(line) == 2  # the review and the learning step
