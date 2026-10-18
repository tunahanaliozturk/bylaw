import json
import subprocess
from pathlib import Path

import pytest

from bylaw.cli import main
from bylaw.local_git import LocalGitSource
from bylaw.source import SourceError


def _git(cwd: Path, *args: str) -> None:
    identity = ["-c", "user.name=Test", "-c", "user.email=test@example.com", "-c", "commit.gpgsign=false"]
    subprocess.run(["git", *identity, *args], cwd=cwd, check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    _git(tmp_path, "init", "-b", "main")
    (tmp_path / ".editorconfig").write_bytes(b"root = true\n[*.py]\nindent_style = space\n")
    (tmp_path / "CONTRIBUTING.md").write_bytes(b"Use parameterised queries, \xe7a va.\n")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-m", "base")
    _git(tmp_path, "checkout", "-b", "feature")
    (tmp_path / "app.py").write_bytes("def run():\n\treturn 'Öztürk'\n".encode())
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-m", "Add app\n\nCloses #7")
    return tmp_path


def test_changed_files_come_from_the_diff_against_the_merge_base(repo: Path) -> None:
    files = LocalGitSource(repo, "main").changed_files()

    assert [(f.path, f.status) for f in files] == [("app.py", "added")]
    assert files[0].added_lines[1].text == "\treturn 'Öztürk'"


def test_base_and_head_reads_see_different_commits(repo: Path) -> None:
    source = LocalGitSource(repo, "main")

    assert "indent_style" in (source.read_base(".editorconfig") or "")
    assert source.read_base("app.py") is None
    assert source.read_head("app.py") is not None


def test_a_base_directory_lists_only_the_files_directly_in_it(repo: Path) -> None:
    _git(repo, "checkout", "-q", "main")
    (repo / "packages" / "api" / "src").mkdir(parents=True)
    (repo / "packages" / "api" / "AGENTS.md").write_text("Return errors as values.\n")
    (repo / "packages" / "api" / "src" / "app.py").write_text("x = 1\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "packages")
    _git(repo, "checkout", "-q", "feature")
    _git(repo, "merge", "-q", "--no-edit", "main")
    (repo / "packages" / "api" / "CLAUDE.md").write_text("only on the branch\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "head only")
    source = LocalGitSource(repo, "main")

    assert source.list_base("packages/api") == {"AGENTS.md"}
    assert source.list_base("") == {".editorconfig", "CONTRIBUTING.md"}
    assert source.list_base("packages") == frozenset()
    assert source.list_base("missing") == frozenset()
    assert source.list_base_tree("packages") == {"packages/api/AGENTS.md", "packages/api/src/app.py"}
    assert source.list_base_tree("") >= {"CONTRIBUTING.md", "packages/api/src/app.py"}
    assert source.read_base_many(["CONTRIBUTING.md", "packages/api/CLAUDE.md"]) == {
        "CONTRIBUTING.md": "Use parameterised queries, �a va.\n",
        "packages/api/CLAUDE.md": None,
    }


def test_undecodable_bytes_are_replaced_instead_of_failing(repo: Path) -> None:
    text = LocalGitSource(repo, "main").read_base("CONTRIBUTING.md")

    assert text is not None
    assert "�" in text


def test_commit_messages_keep_their_closing_keywords(repo: Path) -> None:
    info = LocalGitSource(repo, "main").info()

    assert any("Closes #7" in message for message in info.commit_messages)


def test_an_unknown_base_is_a_source_error(repo: Path) -> None:
    with pytest.raises(SourceError, match="nope"):
        LocalGitSource(repo, "nope")


def test_a_base_that_starts_with_a_dash_is_not_passed_to_git_as_an_option(repo: Path) -> None:
    with pytest.raises(SourceError, match="not a ref"):
        LocalGitSource(repo, "--output=leak.txt")


def test_the_cli_prints_utf8_json_for_a_local_branch(
    repo: Path, capsysbinary: pytest.CaptureFixture[bytes]
) -> None:
    code = main(["context", "--base", "main", "--path", str(repo)])

    output = capsysbinary.readouterr().out.decode("utf-8")
    context = json.loads(output)
    assert code == 0
    assert "Öztürk" in output
    assert [(f["file"], f["evidence"]) for f in context["findings"]] == [("app.py", ".editorconfig:3")]


def test_a_noprefix_git_config_does_not_empty_the_diff(repo: Path) -> None:
    _git(repo, "config", "diff.noprefix", "true")

    files = LocalGitSource(repo, "main").changed_files()

    assert [f.path for f in files] == ["app.py"]


def test_context_writes_utf8_to_the_output_file_and_nothing_to_stdout(
    repo: Path, tmp_path: Path, capsysbinary: pytest.CaptureFixture[bytes]
) -> None:
    out = tmp_path / "out" / "context.json"
    out.parent.mkdir()

    code = main(["context", "--base", "main", "--path", str(repo), "--output", str(out)])

    assert code == 0
    assert capsysbinary.readouterr().out == b""
    assert "Öztürk" in json.loads(out.read_bytes().decode("utf-8"))["files"][0]["patch"]
