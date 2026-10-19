"""bylaw mcp on a pull request with GitHub stubbed out: the post tool, offered only when posting is
allowed, and what the server sends where."""

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from bylaw import cli, mcp_server
from bylaw.mcp_server import make_server
from bylaw.model import Finding, ReviewContext
from tests.unit.test_mcp_server import READ_ONLY_TOOLS, _call, _text, _tools

CONTEXT = ReviewContext.model_validate(
    {
        "base_sha": "b",
        "head_sha": "h",
        "title": "t",
        "files": [{"path": "app.py", "status": "added", "added_lines": [{"number": 1, "text": "x = 1"}]}],
        "rules": [],
        "requirements": [],
        "findings": [],
        "notes": [],
    }
)
FINDING = {
    "file": "app.py",
    "line_start": 1,
    "line_end": 1,
    "category": "bug",
    "severity": "high",
    "message": "m",
}


def test_with_posting_allowed_the_post_tool_is_listed_and_marked_as_writing(tmp_path: Path) -> None:
    tools = _tools(make_server([tmp_path], allow_post=True))

    assert set(tools) == READ_ONLY_TOOLS | {"post"}
    hints = tools["post"].annotations
    assert hints is not None
    assert (hints.read_only_hint, hints.destructive_hint, hints.idempotent_hint) == (False, False, True)


def test_without_posting_allowed_a_call_to_post_is_refused(tmp_path: Path) -> None:
    result = _call(make_server([tmp_path]), "post", {"repo": "acme/app", "pr": 7, "result": {}})

    assert result.is_error
    assert "Unknown tool" in _text(result)


def _stub_github(monkeypatch: pytest.MonkeyPatch, head: str = "h") -> dict[str, Any]:
    """The pull request reads as CONTEXT, now has `head`, and publishing is recorded instead of sent."""
    monkeypatch.setenv("GITHUB_TOKEN", "t")
    published: dict[str, Any] = {}

    class BaseBranch:
        def __init__(self, client: object, repo: str, number: int) -> None:
            pass

        def read_base(self, path: str) -> str | None:
            return "max_comments = 3\n" if path == ".bylaw.toml" else None

        def pull_request(self) -> SimpleNamespace:
            return SimpleNamespace(head=SimpleNamespace(sha=head))

    def publish(_client: object, repo: str, number: int, **parts: Any) -> SimpleNamespace:
        published.update(parts, repo=repo, number=number)
        return SimpleNamespace(inline=("one",), resolve=(), unresolve=())

    monkeypatch.setattr(mcp_server, "build_context", lambda _source, **_: CONTEXT)
    monkeypatch.setattr(mcp_server, "GitHubSource", BaseBranch)
    monkeypatch.setattr(mcp_server, "publish", publish)
    return published


def test_post_refuses_a_pull_request_that_moved_since_the_brief(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    published = _stub_github(monkeypatch, head="pushed-later")

    result = _call(
        make_server([tmp_path], allow_post=True), "post", {"repo": "acme/app", "pr": 7, "result": {}}
    )

    assert result.is_error
    assert "run brief again" in _text(result)
    assert published == {}


def test_post_publishes_the_validated_result_with_the_config_from_the_base_branch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    published = _stub_github(monkeypatch)
    elsewhere = {**FINDING, "file": "other.py"}

    result = _call(
        make_server([tmp_path], allow_post=True),
        "post",
        {"repo": "acme/app", "pr": 7, "result": {"findings": [FINDING, elsewhere]}},
    )

    assert not result.is_error, _text(result)
    assert (published["repo"], published["number"], published["config"].max_comments) == ("acme/app", 7, 3)
    assert published["context"] == CONTEXT
    assert [f.file for f in published["result"].findings] == ["app.py"]
    assert result.structured_content == {
        "inline": 1,
        "resolved": 0,
        "reopened": 0,
        "dropped": ["other.py:1 bug: file is not part of the change"],
    }


def test_bylaw_mcp_allows_posting_only_with_the_allow_post_flag(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    started: list[object] = []

    class Server:
        def run(self, transport: str) -> None:
            started.append(transport)

    def make(_roots: list[Path], *, allow_post: bool = False) -> Server:
        started.append(allow_post)
        return Server()

    monkeypatch.setattr(mcp_server, "make_server", make)

    assert cli.main(["mcp", "--root", str(tmp_path)]) == 0
    assert cli.main(["mcp", "--root", str(tmp_path), "--allow-post"]) == 0
    assert started == [False, "stdio", True, "stdio"]


def test_a_validated_result_fed_back_in_comes_back_clean(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # validate returns bylaw's own findings with the agent's, and the agent sends that result on.
    monkeypatch.setenv("GITHUB_TOKEN", "t")
    own = Finding.model_validate({**FINDING, "message": "found by bylaw's own checks"})
    context = CONTEXT.model_copy(update={"findings": (own,)})
    monkeypatch.setattr(mcp_server, "build_context", lambda _source, **_: context)
    server = make_server([tmp_path])
    target = {"repo": "acme/app", "pr": 7}

    first = _call(server, "validate", {**target, "result": {"findings": [FINDING]}})
    assert first.structured_content is not None
    checked = first.structured_content["result"]
    again = _call(server, "validate", {**target, "result": checked})
    shown = _call(server, "preview", {**target, "result": checked})

    assert len(checked["findings"]) == 2
    assert again.structured_content == {"result": checked, "dropped": []}
    assert shown.structured_content is not None
    assert shown.structured_content["dropped"] == []


def _capture_sites(monkeypatch: pytest.MonkeyPatch) -> list[bool]:
    seen: list[bool] = []

    def build(_source: object, *_args: object, operator_sites: bool = False, **_kw: object) -> ReviewContext:
        seen.append(operator_sites)
        return CONTEXT

    monkeypatch.setattr(mcp_server, "build_context", build)
    return seen


def test_a_pull_request_sends_tracker_tokens_only_to_sites_pinned_in_the_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GITHUB_TOKEN", "t")
    seen = _capture_sites(monkeypatch)

    result = _call(make_server([tmp_path]), "brief", {"repo": "attacker/x", "pr": 1})

    assert not result.is_error, _text(result)
    assert seen == [True]
