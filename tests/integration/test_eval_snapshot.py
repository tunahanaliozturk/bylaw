import base64
import json
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest
import respx

from bylaw.evaluation.cases import Snapshot, build_case_context, load_cases
from bylaw.evaluation.snapshot import freeze, snapshot_pull_request
from bylaw.github import GitHubClient
from bylaw.model import AddedLine, ChangedFile
from tests.unit.fakes import FakeSource

API = "https://api.github.com"
FILES = {
    ("retry.py", "m0"): "def attempts():\n    return None\n",
    ("retry.py", "c2"): "def attempts():\n    return 4\n",
    ("CONTRIBUTING.md", "m0"): "# Contributing\n\n- Cap every loop.\n",
}
PATCH = "@@ -1,2 +1,2 @@\n def attempts():\n-    return None\n+    return 4"


def _graphql(request: httpx.Request) -> httpx.Response:
    query = json.loads(request.content)["query"]
    if "closingIssuesReferences" in query:
        nodes = [{"number": 3, "repository": {"nameWithOwner": "octo/app"}}]
        pull = {"closingIssuesReferences": {"nodes": nodes}}
        return httpx.Response(200, json={"data": {"repository": {"pullRequest": pull}}})
    page = {"pageInfo": {"hasPreviousPage": False, "startCursor": None}, "nodes": []}
    return httpx.Response(200, json={"data": {"repository": {"issue": {"comments": page}}}})


def _contents(request: httpx.Request) -> httpx.Response:
    path = request.url.path.removeprefix("/repos/octo/app/contents/")
    text = FILES.get((path, request.url.params["ref"]))
    return httpx.Response(404, json={}) if text is None else httpx.Response(200, text=text)


@pytest.fixture
def github() -> Iterator[respx.MockRouter]:
    with respx.mock(assert_all_called=False) as router:
        pull = {"title": "Cap retries", "body": "Fixes #3", "base": {"sha": "b1"}, "head": {"sha": "h9"}}
        router.get(f"{API}/repos/octo/app/pulls/7").respond(json={**pull, "user": {"login": "dev"}})
        router.get(f"{API}/repos/octo/app/pulls/comments/99").respond(
            json={
                "html_url": "https://github.com/octo/app/pull/7#discussion_r99",
                "pull_request_url": f"{API}/repos/octo/app/pulls/7",
                "path": "retry.py",
                "original_commit_id": "c2",
                "original_line": 2,
                "body": "Three attempts, the issue says.",
            }
        )
        router.get(f"{API}/repos/octo/app/compare/b1...c2").respond(
            json={
                "merge_base_commit": {"sha": "m0"},
                "commits": [{"commit": {"message": "Cap retries at four"}}],
                "files": [
                    {"filename": "retry.py", "status": "modified", "patch": PATCH, "changes": 2},
                    {
                        "filename": "package-lock.json",
                        "status": "modified",
                        "patch": "@@ -1 +1 @@\n-{\n+[",
                        "changes": 2,
                    },
                ],
            }
        )
        tree = [
            {"path": p, "type": "blob", "sha": "x"}
            for p in ("retry.py", "CONTRIBUTING.md", "package-lock.json")
        ]
        router.get(url__startswith=f"{API}/repos/octo/app/git/trees/m0").respond(json={"tree": tree})
        router.get(url__startswith=f"{API}/repos/octo/app/contents/").mock(side_effect=_contents)
        router.get(f"{API}/repos/octo/app/issues/3").respond(
            json={"title": "Retries never stop", "body": "- [ ] stop after 3"}
        )
        router.post(f"{API}/graphql").mock(side_effect=_graphql)
        licence = base64.b64encode(b"MIT License\n\nCopyright (c) Octo\n").decode()
        router.get(f"{API}/repos/octo/app/license").respond(
            json={"path": "LICENSE", "content": licence, "license": {"spdx_id": "MIT"}}
        )
        yield router


def _snapshot(root: Path, comment: int | None = 99) -> Snapshot:
    with GitHubClient("token") as client:
        return snapshot_pull_request(client, "octo/app", 7, comment, root / "cases" / "octo-app-7")


def test_a_snapshot_freezes_the_reviewed_commit_its_rules_issue_and_licence(
    github: respx.MockRouter, tmp_path: Path
) -> None:
    pull = _snapshot(tmp_path)

    case = tmp_path / "cases/octo-app-7"
    assert sorted(p.relative_to(case).as_posix() for p in case.rglob("*") if p.is_file()) == [
        "LICENSE",
        "base/CONTRIBUTING.md",
        "base/retry.py",
        "head/retry.py",
        "snapshot.json",
    ]
    assert (case / "head/retry.py").read_bytes() == b"def attempts():\n    return 4\n"
    assert (pull.base_sha, pull.head_sha, pull.licence) == ("m0", "c2", "MIT")
    assert pull.commit_messages == ("Cap retries at four",)
    assert pull.left_out == ("package-lock.json",)
    assert [(i.number, i.title) for i in pull.issues] == [(3, "Retries never stop")]
    assert pull.evidence is not None
    assert (pull.evidence.path, pull.evidence.lines) == ("retry.py", (2, 2))
    # Rule files the tree says are missing are never asked for: the tree read saves those calls.
    asked = {call.request.url.path for call in github.calls}
    assert f"/repos/octo/app/contents/{'AGENTS.md'}" not in asked


@pytest.mark.usefixtures("github")
def test_a_snapshot_replays_as_a_case_that_shows_the_same_change(tmp_path: Path) -> None:
    _snapshot(tmp_path)
    (tmp_path / "cases/octo-app-7/case.toml").write_text('kind = "clean"\nlabellers = ["ada"]\n', "utf-8")
    (case,) = load_cases(tmp_path)

    with respx.mock:  # any request from here on fails the test
        context = build_case_context(tmp_path, case, tmp_path / "work")

    assert [(f.path, [line.number for line in f.added_lines]) for f in context.files] == [("retry.py", [2])]
    assert [r.source for r in context.requirements] == ["issue#3"]


def test_without_a_comment_the_snapshot_is_the_merged_head(github: respx.MockRouter, tmp_path: Path) -> None:
    github.get(f"{API}/repos/octo/app/compare/b1...h9").respond(
        json={"merge_base_commit": {"sha": "m0"}, "commits": [], "files": []}
    )

    pull = _snapshot(tmp_path, comment=None)

    assert (pull.head_sha, pull.evidence) == ("h9", None)


def test_a_project_without_a_permissive_licence_is_refused(github: respx.MockRouter, tmp_path: Path) -> None:
    github.get(f"{API}/repos/octo/app/license").respond(
        json={"path": "COPYING", "content": "", "license": {"spdx_id": "GPL-3.0"}}
    )

    with pytest.raises(ValueError, match=r"GPL-3\.0"):
        _snapshot(tmp_path)
    assert not (tmp_path / "cases").exists()


def test_a_comment_on_another_pull_request_is_refused(github: respx.MockRouter, tmp_path: Path) -> None:
    github.get(f"{API}/repos/octo/app/pulls/comments/99").respond(
        json={
            "html_url": "u",
            "pull_request_url": f"{API}/repos/octo/app/pulls/8",
            "path": "retry.py",
            "original_commit_id": "c2",
        }
    )

    with pytest.raises(ValueError, match="pull request 8"):
        _snapshot(tmp_path)


def test_a_snapshot_that_does_not_reproduce_the_diff_is_refused(tmp_path: Path) -> None:
    # GitHub says line 5 was added, but the file has two lines: the snapshot would not show the same change.
    claimed = ChangedFile(path="a.py", status="added", added_lines=(AddedLine(number=5, text="x"),))
    source = FakeSource(files=(claimed,), head={"a.py": "x\ny\n"})

    with pytest.raises(ValueError, match=r"does not reproduce .*a\.py"):
        freeze(source, tmp_path / "cases/c", url="u", number=1, licence=("MIT", "LICENSE", "MIT License\n"))


def test_a_path_that_leaves_the_case_directory_is_refused(tmp_path: Path) -> None:
    escape = ChangedFile(path="../evil.py", status="added", added_lines=(AddedLine(number=1, text="x"),))
    source = FakeSource(files=(escape,), head={"../evil.py": "x\n"})

    with pytest.raises(ValueError, match="evil"):
        freeze(source, tmp_path / "cases/c", url="u", number=1, licence=("MIT", "LICENSE", "MIT License\n"))
    assert not (tmp_path / "cases/evil.py").exists()


@pytest.mark.usefixtures("github")
def test_freezing_again_keeps_the_labels(tmp_path: Path) -> None:
    _snapshot(tmp_path)
    labels = tmp_path / "cases/octo-app-7/case.toml"
    labels.write_bytes(b'kind = "bug"\nlabellers = ["ada"]\n')
    (tmp_path / "cases/octo-app-7/head/stale.py").write_bytes(b"old\n")

    _snapshot(tmp_path)

    assert labels.read_bytes() == b'kind = "bug"\nlabellers = ["ada"]\n'
    assert not (tmp_path / "cases/octo-app-7/head/stale.py").exists()
