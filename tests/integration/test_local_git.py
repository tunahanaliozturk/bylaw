import subprocess
from pathlib import Path

import pytest

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
