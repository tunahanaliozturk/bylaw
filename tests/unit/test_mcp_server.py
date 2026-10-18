"""bylaw mcp through an in-process MCP client: the tools it lists and how it refuses bad targets."""

from pathlib import Path
from typing import Any

import anyio
import httpx
import pytest
import respx
from mcp import Client
from mcp.types import CallToolResult, TextContent, Tool

from bylaw.engine import OutReview
from bylaw.mcp_server import make_server

READ_ONLY_TOOLS = {"context", "brief", "schema", "validate", "preview"}


@pytest.fixture(autouse=True)
def github_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("GITHUB_TOKEN", "GH_TOKEN", "GITHUB_API_URL", "GITHUB_GRAPHQL_URL"):
        monkeypatch.delenv(name, raising=False)


def _tools(server: Any) -> dict[str, Tool]:
    async def go() -> dict[str, Tool]:
        async with Client(server) as client:
            return {tool.name: tool for tool in (await client.list_tools()).tools}

    return anyio.run(go)


def _call(server: Any, name: str, arguments: dict[str, Any] | None = None) -> CallToolResult:
    async def go() -> CallToolResult:
        async with Client(server) as client:
            return await client.call_tool(name, arguments or {})

    return anyio.run(go)


def _text(result: CallToolResult) -> str:
    return "".join(block.text for block in result.content if isinstance(block, TextContent))


def test_by_default_only_the_read_only_tools_are_listed(tmp_path: Path) -> None:
    tools = _tools(make_server([tmp_path]))

    assert set(tools) == READ_ONLY_TOOLS
    assert all(t.annotations is not None and t.annotations.read_only_hint for t in tools.values())


def test_every_tool_says_what_it_is_for(tmp_path: Path) -> None:
    tools = _tools(make_server([tmp_path]))

    assert all(t.description for t in tools.values())


def test_the_schema_tool_returns_the_shape_a_result_must_follow(tmp_path: Path) -> None:
    result = _call(make_server([tmp_path]), "schema")

    assert not result.is_error
    assert result.structured_content == OutReview.model_json_schema()


def test_naming_both_a_pull_request_and_a_base_is_an_error(tmp_path: Path) -> None:
    result = _call(make_server([tmp_path]), "context", {"repo": "acme/app", "pr": 1, "base": "main"})

    assert result.is_error
    assert "either pr or base" in _text(result)


def test_naming_neither_a_pull_request_nor_a_base_is_an_error(tmp_path: Path) -> None:
    result = _call(make_server([tmp_path]), "brief", {})

    assert result.is_error
    assert "either pr or base" in _text(result)


@pytest.mark.parametrize("repo", ["../../user", "acme/app/issues", "acme", "acme/app?x=1", ""])
def test_a_repository_that_is_not_owner_slash_name_is_refused(tmp_path: Path, repo: str) -> None:
    result = _call(make_server([tmp_path]), "context", {"repo": repo, "pr": 1})

    assert result.is_error
    assert "owner/name" in _text(result)


def test_a_pull_request_without_a_token_names_the_variables_to_set(tmp_path: Path) -> None:
    result = _call(make_server([tmp_path]), "context", {"repo": "acme/app", "pr": 1})

    assert result.is_error
    assert "GITHUB_TOKEN or GH_TOKEN" in _text(result)


def test_a_github_failure_is_reported_without_the_token(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_sentinel_value_never_shown")

    with respx.mock(assert_all_called=False) as github:
        github.route().mock(return_value=httpx.Response(401, json={"message": "Bad credentials"}))
        result = _call(make_server([tmp_path]), "context", {"repo": "acme/app", "pr": 1})
        assert github.calls, "the tool should have asked GitHub"

    assert result.is_error
    assert "401" in _text(result)
    assert "sentinel" not in _text(result)


def test_a_root_that_is_not_a_directory_is_refused_at_start(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="not a directory"):
        make_server([tmp_path / "missing"])
