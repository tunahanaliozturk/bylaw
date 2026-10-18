"""bylaw mcp on a local repository, through an in-process client and once over stdio."""

import subprocess
import sys
from pathlib import Path
from typing import Any

import anyio
import pytest
from mcp import Client
from mcp.client.stdio import StdioServerParameters
from mcp.types import CallToolResult, TextContent

from bylaw.mcp_server import make_server
from bylaw.model import ReviewContext
from bylaw.prompt import system_prompt

FINDING = {
    "file": "app.py",
    "line_start": 2,
    "line_end": 2,
    "category": "security",
    "severity": "high",
    "message": "SQL built from input",
}


def _git(cwd: Path, *args: str) -> str:
    identity = ["-c", "user.name=Test", "-c", "user.email=test@example.com", "-c", "commit.gpgsign=false"]
    done = subprocess.run(["git", *identity, *args], cwd=cwd, check=True, capture_output=True, text=True)
    return done.stdout.strip()


def _repository(root: Path) -> Path:
    root.mkdir(parents=True)
    _git(root, "init", "-b", "main")
    (root / "CONTRIBUTING.md").write_text("Use parameterised queries.\n", encoding="utf-8")
    _git(root, "add", ".")
    _git(root, "commit", "-m", "base")
    _git(root, "checkout", "-b", "feature")
    (root / "app.py").write_text(
        "def run(db, name):\n    return db.execute(f'SELECT {name}')\n", encoding="utf-8"
    )
    _git(root, "add", ".")
    _git(root, "commit", "-m", "Add app")
    return root


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    return _repository(tmp_path / "repo")


def _call(server: Any, name: str, arguments: dict[str, Any]) -> CallToolResult:
    async def go() -> CallToolResult:
        async with Client(server) as client:
            return await client.call_tool(name, arguments)

    return anyio.run(go)


def _text(result: CallToolResult) -> str:
    return "".join(block.text for block in result.content if isinstance(block, TextContent))


def test_the_context_is_the_review_context_of_the_branch(repo: Path) -> None:
    result = _call(make_server([repo]), "context", {"base": "main"})

    assert not result.is_error, _text(result)
    context = ReviewContext.model_validate_json(_text(result))
    assert [f.path for f in context.files] == ["app.py"]
    assert context.head_sha == _git(repo, "rev-parse", "HEAD")


def test_the_brief_is_bylaw_s_instructions_then_the_review_data(repo: Path) -> None:
    result = _call(make_server([repo]), "brief", {"base": "main"})

    assert not result.is_error, _text(result)
    assert _text(result).startswith(f"{system_prompt()}\n---\n")
    assert "db.execute(f'SELECT {name}')" in _text(result)
    assert "Use parameterised queries." in _text(result)


def test_validate_keeps_a_finding_on_the_change_and_says_why_it_dropped_another(repo: Path) -> None:
    elsewhere = {**FINDING, "file": "other.py"}

    result = _call(
        make_server([repo]), "validate", {"base": "main", "result": {"findings": [FINDING, elsewhere]}}
    )

    assert not result.is_error, _text(result)
    assert result.structured_content is not None
    assert [f["file"] for f in result.structured_content["result"]["findings"]] == ["app.py"]
    assert result.structured_content["dropped"] == ["other.py:2 security: file is not part of the change"]


def test_a_result_that_breaks_the_schema_is_an_error_the_agent_can_read(repo: Path) -> None:
    result = _call(
        make_server([repo]), "validate", {"base": "main", "result": {"findings": [{"file": "app.py"}]}}
    )

    assert result.is_error
    assert "line_start" in _text(result)


def test_preview_shows_the_review_that_would_be_posted(repo: Path) -> None:
    result = _call(make_server([repo]), "preview", {"base": "main", "result": {"findings": [FINDING]}})

    assert not result.is_error, _text(result)
    assert result.structured_content is not None
    assert "SQL built from input" in result.structured_content["markdown"]
    assert result.structured_content["dropped"] == []


def test_validate_judges_a_result_against_the_context_the_brief_was_built_from(repo: Path) -> None:
    server = make_server([repo])
    _call(server, "brief", {"base": "main"})
    with (repo / "app.py").open("a", encoding="utf-8") as file:
        file.write("    # pushed after the brief\n")
    _git(repo, "commit", "-am", "later")
    later = {**FINDING, "line_start": 3, "line_end": 3}

    result = _call(server, "validate", {"base": "main", "result": {"findings": [later]}})

    assert result.structured_content is not None
    assert result.structured_content["result"]["findings"] == []
    assert len(result.structured_content["dropped"]) == 1


def test_a_new_brief_reads_the_branch_again(repo: Path) -> None:
    server = make_server([repo])
    _call(server, "brief", {"base": "main"})
    with (repo / "app.py").open("a", encoding="utf-8") as file:
        file.write("    # pushed after the brief\n")
    _git(repo, "commit", "-am", "later")

    assert "pushed after the brief" in _text(_call(server, "brief", {"base": "main"}))


def test_a_path_is_read_relative_to_the_first_root(tmp_path: Path) -> None:
    _repository(tmp_path / "work" / "app")

    result = _call(make_server([tmp_path / "work"]), "context", {"base": "main", "path": "app"})

    assert not result.is_error, _text(result)


def test_a_path_outside_the_allowed_roots_is_refused(repo: Path, tmp_path: Path) -> None:
    outside = _repository(tmp_path / "outside")

    for path in (str(outside), "../outside"):
        result = _call(make_server([repo]), "context", {"base": "main", "path": path})

        assert result.is_error
        assert "outside the allowed roots" in _text(result)


def test_a_folder_in_the_root_that_belongs_to_a_repository_above_it_is_refused(repo: Path) -> None:
    (repo / "docs").mkdir()

    result = _call(make_server([repo / "docs"]), "context", {"base": "main"})

    assert result.is_error
    assert "outside the allowed roots" in _text(result)


def test_a_base_that_looks_like_an_option_is_refused(repo: Path) -> None:
    result = _call(make_server([repo]), "context", {"base": "--output=leak.txt"})

    assert result.is_error
    assert "not a ref" in _text(result)
    assert not (repo / "leak.txt").exists()


def test_bylaw_mcp_serves_the_tools_over_stdio(repo: Path) -> None:
    params = StdioServerParameters(command=sys.executable, args=["-m", "bylaw", "mcp", "--root", str(repo)])

    async def go() -> tuple[set[str], CallToolResult]:
        async with Client(params) as client:
            names = {tool.name for tool in (await client.list_tools()).tools}
            return names, await client.call_tool("validate", {"base": "main", "result": {}})

    names, result = anyio.run(go)

    assert names == {"context", "brief", "schema", "validate", "preview"}
    assert not result.is_error, _text(result)
