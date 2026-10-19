from collections.abc import Iterator

import httpx
import pytest
import respx

from bylaw.gitlab import GitLabClient, GitLabError, GitLabMergeRequest
from bylaw.source import SourceError

API = "https://gitlab.example.com/api/v4"
P = f"{API}/projects/42"
TOKEN = "glpat-secret-token"  # noqa: S105 - a fake token the error message must not echo
MR = {
    "iid": 5,
    "title": "Add parser",
    "description": "Closes #12",
    "author": {"id": 7, "username": "dev"},
    "references": {"full": "Group/App!5"},
    "diff_refs": {"base_sha": "b1", "start_sha": "s1", "head_sha": "h1"},
}


@pytest.fixture
def client() -> Iterator[GitLabClient]:
    with GitLabClient(TOKEN, API) as gitlab:
        yield gitlab


def _mr(client: GitLabClient) -> GitLabMergeRequest:
    return GitLabMergeRequest(client, "42", 5)


def _serve_mr(body: dict[str, object] | None = None) -> None:
    respx.get(f"{P}/merge_requests/5").mock(return_value=httpx.Response(200, json=body or MR))


def _member(user_id: int, level: int | None) -> None:
    route = respx.get(f"{P}/members/all/{user_id}")
    if level is None:
        route.mock(return_value=httpx.Response(404, json={"message": "404 Not found"}))
    else:
        route.mock(return_value=httpx.Response(200, json={"id": user_id, "access_level": level}))


@respx.mock
def test_info_reads_the_title_description_shas_and_commit_messages(client: GitLabClient) -> None:
    _serve_mr()
    respx.get(url__startswith=f"{P}/merge_requests/5/diffs").mock(return_value=httpx.Response(200, json=[]))
    _member(7, 30)
    respx.get(url__startswith=f"{P}/merge_requests/5/commits").mock(
        return_value=httpx.Response(200, json=[{"message": "Fixes #3"}, {"message": "Tidy"}])
    )

    info = _mr(client).info()

    # The base is the target branch commit (start_sha), as GitHub's base sha is (ADR 0004, ADR 0020).
    assert (info.base_sha, info.head_sha, info.title, info.body) == ("s1", "h1", "Add parser", "Closes #12")
    assert (info.commit_messages, info.author_trusted, info.file_count) == (("Fixes #3", "Tidy"), True, None)


@respx.mock
@pytest.mark.parametrize("level", [20, None])
def test_an_author_below_developer_or_outside_the_project_is_not_trusted(
    client: GitLabClient, level: int | None
) -> None:
    _serve_mr()
    respx.get(url__startswith=f"{P}/merge_requests/5/diffs").mock(return_value=httpx.Response(200, json=[]))
    _member(7, level)
    respx.get(url__startswith=f"{P}/merge_requests/5/commits").mock(return_value=httpx.Response(200, json=[]))

    assert _mr(client).info().author_trusted is False


@respx.mock
def test_a_merge_request_whose_diff_is_not_ready_asks_for_a_rerun(client: GitLabClient) -> None:
    _serve_mr({**MR, "diff_refs": None})

    with pytest.raises(SourceError, match="has not finished computing"):
        _mr(client).info()


@respx.mock
def test_every_page_of_diffs_is_collected_with_status_and_added_lines(client: GitLabClient) -> None:
    _serve_mr()
    page_one = [
        {"old_path": f"f{i}.py", "new_path": f"f{i}.py", "diff": "@@ -1 +1 @@\n-a\n+b\n"} for i in range(100)
    ]
    page_two = [
        {"old_path": "new.py", "new_path": "new.py", "new_file": True, "diff": "@@ -0,0 +1 @@\n+x\n"},
        {"old_path": "old.py", "new_path": "moved.py", "renamed_file": True, "diff": "@@ -1 +1 @@\n-a\n+c\n"},
        {"old_path": "gone.py", "new_path": "gone.py", "deleted_file": True, "diff": "@@ -1 +0,0 @@\n-a\n"},
    ]
    second = f"{P}/merge_requests/5/diffs?page=2&per_page=100"

    def serve(request: httpx.Request) -> httpx.Response:
        if request.url.params.get("page") == "2":
            return httpx.Response(200, json=page_two)
        return httpx.Response(200, json=page_one, headers={"link": f'<{second}>; rel="next"'})

    respx.get(url__startswith=f"{P}/merge_requests/5/diffs").mock(side_effect=serve)

    files = _mr(client).changed_files()

    assert len(files) == 103
    assert [(f.path, f.status, f.previous_path) for f in files[-3:]] == [
        ("new.py", "added", None),
        ("moved.py", "renamed", "old.py"),
        ("gone.py", "removed", None),
    ]
    assert files[-3].added_lines[0].number == 1


@respx.mock
def test_a_push_while_the_diff_is_read_makes_bylaw_read_the_newer_one(client: GitLabClient) -> None:
    newer = {**MR, "diff_refs": {"base_sha": "b2", "start_sha": "s2", "head_sha": "h2"}}
    respx.get(f"{P}/merge_requests/5").mock(
        side_effect=[
            httpx.Response(200, json=MR),
            httpx.Response(200, json=newer),
            httpx.Response(200, json=newer),
        ]
    )
    _member(7, 30)
    respx.get(url__startswith=f"{P}/merge_requests/5/commits").mock(return_value=httpx.Response(200, json=[]))
    old = [{"old_path": "a.py", "new_path": "a.py", "diff": "@@ -1 +1 @@\n-a\n+b\n"}]
    new = [{"old_path": "a.py", "new_path": "a.py", "diff": "@@ -1 +1,2 @@\n-a\n+b\n+c\n"}]
    respx.get(url__startswith=f"{P}/merge_requests/5/diffs").mock(
        side_effect=[httpx.Response(200, json=old), httpx.Response(200, json=new)]
    )
    mr = _mr(client)

    info = mr.info()

    # The shas and the diff are read as one: the newer head with the newer diff.
    assert (info.base_sha, info.head_sha) == ("s2", "h2")
    assert [line.number for line in mr.changed_files()[0].added_lines] == [1, 2]


@respx.mock
def test_a_merge_request_that_keeps_changing_asks_for_a_rerun(client: GitLabClient) -> None:
    heads = iter(range(100))

    def serve(_request: httpx.Request) -> httpx.Response:
        head = f"h{next(heads)}"
        return httpx.Response(
            200, json={**MR, "diff_refs": {"base_sha": "b", "start_sha": "s", "head_sha": head}}
        )

    respx.get(f"{P}/merge_requests/5").mock(side_effect=serve)
    respx.get(url__startswith=f"{P}/merge_requests/5/diffs").mock(return_value=httpx.Response(200, json=[]))

    with pytest.raises(SourceError, match="kept changing"):
        _mr(client).changed_files()


@respx.mock
def test_a_binary_too_large_or_empty_diff_is_marked_omitted(client: GitLabClient) -> None:
    _serve_mr()
    diffs = [
        {
            "old_path": "logo.png",
            "new_path": "logo.png",
            "diff": "Binary files a/logo.png and b/logo.png differ\n",
        },
        {"old_path": "huge.sql", "new_path": "huge.sql", "diff": "", "too_large": True},
        {"old_path": "big.json", "new_path": "big.json", "diff": "", "collapsed": True},
        {"old_path": "a.sh", "new_path": "a.sh", "diff": "", "a_mode": "100644", "b_mode": "100755"},
    ]
    respx.get(url__startswith=f"{P}/merge_requests/5/diffs").mock(
        return_value=httpx.Response(200, json=diffs)
    )

    files = _mr(client).changed_files()

    assert [(f.patch_omitted, f.changes) for f in files] == [(True, None), (True, 1), (True, 1), (True, 0)]


@respx.mock
def test_base_reads_use_the_target_branch_commit_and_a_missing_file_is_none(client: GitLabClient) -> None:
    _serve_mr()
    found = respx.get(url__startswith=f"{P}/repository/files/docs%2FCONTRIBUTING.md/raw").mock(
        return_value=httpx.Response(200, text="Be kind.")
    )
    respx.get(url__startswith=f"{P}/repository/files/.bylaw.toml/raw").mock(
        return_value=httpx.Response(404, json={"message": "404 File Not Found"})
    )
    mr = _mr(client)

    assert mr.read_base("docs/CONTRIBUTING.md") == "Be kind."
    assert mr.read_base(".bylaw.toml") is None
    assert found.calls.last.request.url.params["ref"] == "s1"
    assert mr.read_base_many(["docs/CONTRIBUTING.md", ".bylaw.toml"]) == {
        "docs/CONTRIBUTING.md": "Be kind.",
        ".bylaw.toml": None,
    }


@respx.mock
def test_head_reads_use_the_head_commit(client: GitLabClient) -> None:
    _serve_mr()
    route = respx.get(url__startswith=f"{P}/repository/files/spec.md/raw").mock(
        return_value=httpx.Response(200, text="# Spec")
    )

    assert _mr(client).read_head("spec.md") == "# Spec"
    assert route.calls.last.request.url.params["ref"] == "h1"


@respx.mock
def test_a_directory_listing_names_only_its_files_and_a_missing_one_is_empty(client: GitLabClient) -> None:
    _serve_mr()
    entries = [
        {"type": "blob", "name": "AGENTS.md", "path": "pkg/AGENTS.md"},
        {"type": "tree", "name": "sub", "path": "pkg/sub"},
    ]

    def serve(request: httpx.Request) -> httpx.Response:
        if request.url.params.get("path") == "pkg":
            assert (request.url.params["ref"], request.url.params.get("recursive")) == ("s1", None)
            return httpx.Response(200, json=entries)
        return httpx.Response(404, json={"message": "404 Tree Not Found"})

    respx.get(url__startswith=f"{P}/repository/tree").mock(side_effect=serve)
    mr = _mr(client)

    assert mr.list_base("pkg") == frozenset({"AGENTS.md"})
    assert mr.list_base("nowhere") == frozenset()


@respx.mock
def test_a_tree_listing_walks_every_subdirectory(client: GitLabClient) -> None:
    _serve_mr()
    entries = [
        {"type": "blob", "name": "0001-a.md", "path": "docs/adr/0001-a.md"},
        {"type": "tree", "name": "old", "path": "docs/adr/old"},
        {"type": "blob", "name": "0002-b.md", "path": "docs/adr/old/0002-b.md"},
    ]
    route = respx.get(url__startswith=f"{P}/repository/tree").mock(
        return_value=httpx.Response(200, json=entries)
    )

    paths = _mr(client).list_base_tree("docs/adr")

    assert paths == frozenset({"docs/adr/0001-a.md", "docs/adr/old/0002-b.md"})
    assert route.calls.last.request.url.params["recursive"] == "true"


@respx.mock
def test_the_repository_is_the_project_path_in_lower_case(client: GitLabClient) -> None:
    _serve_mr()

    assert _mr(client).repo == "group/app"


@respx.mock
def test_an_api_error_names_the_status_and_never_the_token(client: GitLabClient) -> None:
    respx.get(f"{P}/merge_requests/5").mock(
        return_value=httpx.Response(401, json={"message": "401 Unauthorized"})
    )

    with pytest.raises(GitLabError) as error:
        _mr(client).info()

    assert "401" in str(error.value)
    assert TOKEN not in str(error.value)


@respx.mock
def test_a_next_page_link_to_another_host_is_not_followed_with_the_token(client: GitLabClient) -> None:
    _serve_mr()
    elsewhere = respx.get(url__startswith="https://elsewhere.example/")
    respx.get(url__startswith=f"{P}/merge_requests/5/diffs").mock(
        return_value=httpx.Response(
            200, json=[], headers={"link": '<https://elsewhere.example/api/v4/next>; rel="next"'}
        )
    )

    with pytest.raises(GitLabError, match="another address"):
        _mr(client).changed_files()

    assert not elsewhere.called


@respx.mock
def test_requests_carry_the_token_in_the_private_token_header(client: GitLabClient) -> None:
    route = respx.get(f"{P}/merge_requests/5").mock(return_value=httpx.Response(200, json=MR))

    assert _mr(client).repo == "group/app"
    assert route.calls.last.request.headers["PRIVATE-TOKEN"] == TOKEN
