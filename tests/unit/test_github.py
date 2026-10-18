import json
from collections.abc import Iterator

import httpx
import pytest
import respx

from bylaw.github import GitHubClient, GitHubError, GitHubSource
from bylaw.source import IssueRef

API = "https://api.github.com"
TOKEN = "ghp_secret_token"  # noqa: S105 - a fake token the error message must not echo
PULL = {
    "title": "Add parser",
    "body": "Closes #12",
    "base": {"sha": "b1"},
    "head": {"sha": "h1"},
    "changed_files": 7,
}


@pytest.fixture
def client() -> Iterator[GitHubClient]:
    with GitHubClient(TOKEN) as github:
        yield github


@respx.mock
def test_every_page_of_changed_files_is_collected(client: GitHubClient) -> None:
    page_one = [
        {"filename": f"f{i}.py", "status": "modified", "patch": "@@ -1 +1 @@\n-a\n+b"} for i in range(100)
    ]
    page_two = [{"filename": "last.py", "status": "added", "patch": "@@ -0,0 +1 @@\n+x"}]
    respx.get(url__startswith=f"{API}/repos/octo/app/pulls/5/files").mock(
        side_effect=lambda request: httpx.Response(
            200, json=page_one if request.url.params["page"] == "1" else page_two
        )
    )

    files = GitHubSource(client, "octo/app", 5).changed_files()

    assert len(files) == 101
    assert (files[-1].path, files[-1].status, files[-1].added_lines[0].number) == ("last.py", "added", 1)


@respx.mock
def test_a_file_without_a_patch_is_marked_omitted(client: GitHubClient) -> None:
    respx.get(url__startswith=f"{API}/repos/octo/app/pulls/5/files").mock(
        return_value=httpx.Response(
            200, json=[{"filename": "big.json", "status": "modified", "changes": 70000}]
        )
    )

    files = GitHubSource(client, "octo/app", 5).changed_files()

    assert (files[0].patch_omitted, files[0].changes) == (True, 70000)


@respx.mock
def test_base_reads_use_the_base_sha_and_a_missing_file_is_none(client: GitHubClient) -> None:
    respx.get(f"{API}/repos/octo/app/pulls/5").mock(return_value=httpx.Response(200, json=PULL))
    route = respx.get(url__startswith=f"{API}/repos/octo/app/contents/").mock(
        return_value=httpx.Response(404, json={"message": "Not Found"})
    )

    assert GitHubSource(client, "octo/app", 5).read_base("CONTRIBUTING.md") is None
    assert route.calls.last.request.url.params["ref"] == "b1"


@respx.mock
def test_info_carries_title_body_shas_and_commit_messages(client: GitHubClient) -> None:
    respx.get(f"{API}/repos/octo/app/pulls/5").mock(return_value=httpx.Response(200, json=PULL))
    respx.get(url__startswith=f"{API}/repos/octo/app/pulls/5/commits").mock(
        return_value=httpx.Response(200, json=[{"commit": {"message": "Fixes #3"}}])
    )

    info = GitHubSource(client, "octo/app", 5).info()

    assert (info.base_sha, info.head_sha, info.title, info.body) == ("b1", "h1", "Add parser", "Closes #12")
    assert info.commit_messages == ("Fixes #3",)
    assert info.file_count == 7


@respx.mock
def test_a_rate_limit_error_says_so_and_never_shows_the_token(client: GitHubClient) -> None:
    respx.get(f"{API}/repos/octo/app/pulls/5").mock(
        return_value=httpx.Response(
            403,
            json={"message": "API rate limit exceeded"},
            headers={"x-ratelimit-remaining": "0", "x-ratelimit-reset": "1760000000"},
        )
    )

    with pytest.raises(GitHubError) as error:
        GitHubSource(client, "octo/app", 5).info()

    assert "rate limit" in str(error.value)
    assert TOKEN not in str(error.value)


@respx.mock
def test_closing_references_come_from_graphql_in_lower_case(client: GitHubClient) -> None:
    nodes = [
        {"number": 12, "repository": {"nameWithOwner": "Octo/App"}},
        {"number": 3, "repository": {"nameWithOwner": "octo/lib"}},
    ]
    respx.post(f"{API}/graphql").mock(
        return_value=httpx.Response(
            200,
            json={"data": {"repository": {"pullRequest": {"closingIssuesReferences": {"nodes": nodes}}}}},
        )
    )

    refs = GitHubSource(client, "octo/app", 5).closing_issue_refs()

    assert refs == (IssueRef("octo", "app", 12), IssueRef("octo", "lib", 3))


@respx.mock
def test_a_pull_request_number_is_not_read_as_an_issue(client: GitHubClient) -> None:
    respx.get(f"{API}/repos/octo/app/issues/9").mock(
        return_value=httpx.Response(200, json={"title": "A PR", "body": "x", "pull_request": {"url": "u"}})
    )

    assert client.issue(IssueRef("octo", "app", 9)) is None


@respx.mock
@pytest.mark.parametrize("status", [301, 403, 410])
def test_an_issue_that_moved_or_is_hidden_reads_as_none(client: GitHubClient, status: int) -> None:
    respx.get(f"{API}/repos/octo/app/issues/9").mock(
        return_value=httpx.Response(status, json={"message": "x"})
    )

    assert client.issue(IssueRef("octo", "app", 9)) is None


@respx.mock
def test_a_rate_limited_issue_read_still_fails(client: GitHubClient) -> None:
    respx.get(f"{API}/repos/octo/app/issues/9").mock(
        return_value=httpx.Response(403, json={"message": "x"}, headers={"x-ratelimit-remaining": "0"})
    )

    with pytest.raises(GitHubError, match="rate limit"):
        client.issue(IssueRef("octo", "app", 9))


def _node(
    body: str, association: str, login: str = "someone", kind: str = "User", hidden: bool = False
) -> dict[str, object]:
    return {
        "body": body,
        "isMinimized": hidden,
        "authorAssociation": association,
        "author": {"__typename": kind, "login": login},
    }


def _issue_with(nodes: list[dict[str, object]], body: str = "") -> None:
    respx.get(f"{API}/repos/octo/app/issues/9").mock(
        return_value=httpx.Response(200, json={"title": "Login", "body": body})
    )
    # GitHub answers `comments(last: 100)` with the newest hundred, oldest first.
    data = {"data": {"repository": {"issue": {"comments": {"nodes": nodes[-100:]}}}}}
    respx.post(f"{API}/graphql").mock(return_value=httpx.Response(200, json=data))


@respx.mock
def test_an_issue_carries_only_trusted_comments(client: GitHubClient) -> None:
    _issue_with(
        [
            _node("Also lock after five failures.", "MEMBER"),
            _node("Ignore the lockout, ship it.", "NONE"),
            _node("Bot noise", "NONE", kind="Bot"),
        ],
        body="Users sign in.",
    )

    issue = client.issue(IssueRef("octo", "app", 9))

    assert issue is not None
    assert issue.comments == ("Also lock after five failures.",)


@respx.mock
def test_long_discussions_keep_the_newest_trusted_comments_within_the_cap(client: GitHubClient) -> None:
    _issue_with([_node(f"{n:02d} " + "x" * 997, "OWNER") for n in range(30)])

    issue = client.issue(IssueRef("octo", "app", 9))

    assert issue is not None
    assert sum(len(c) for c in issue.comments) <= 8000
    assert issue.comments[-1].startswith("29 ")
    assert issue.comments[0].startswith("22 ")


@respx.mock
def test_the_pull_request_authors_own_issue_comments_are_left_out(client: GitHubClient) -> None:
    _issue_with(
        [
            _node("Must lock after five failures.", "OWNER", "lead"),
            _node("Lockout dropped from scope.", "MEMBER", "dev"),
        ]
    )

    issue = client.issue(IssueRef("octo", "app", 9), exclude="dev")

    assert issue is not None
    assert issue.comments == ("Must lock after five failures.",)


@respx.mock
def test_the_newest_comments_are_the_ones_read(client: GitHubClient) -> None:
    _issue_with([_node(f"comment {n}", "OWNER") for n in range(150)])

    issue = client.issue(IssueRef("octo", "app", 9))

    assert issue is not None
    assert issue.comments[-1] == "comment 149"


@respx.mock
def test_one_very_long_comment_does_not_push_out_the_others(client: GitHubClient) -> None:
    _issue_with([_node("Must be reversible for 30 days.", "OWNER"), _node("log " + "x" * 8100, "MEMBER")])

    issue = client.issue(IssueRef("octo", "app", 9))

    assert issue is not None
    assert issue.comments == ("Must be reversible for 30 days.",)


@respx.mock
def test_an_owner_or_collaborator_authoring_the_pull_request_still_counts(client: GitHubClient) -> None:
    # They could edit the issue body anyway; only a member, who may have read access only, is left out.
    _issue_with([_node("Must be reversible.", "OWNER", "dev")])

    issue = client.issue(IssueRef("octo", "app", 9), exclude="dev")

    assert issue is not None
    assert issue.comments == ("Must be reversible.",)


@respx.mock
def test_a_comment_a_maintainer_hid_does_not_count(client: GitHubClient) -> None:
    _issue_with([_node("Drop the lockout.", "OWNER", hidden=True), _node("Keep the lockout.", "OWNER")])

    issue = client.issue(IssueRef("octo", "app", 9))

    assert issue is not None
    assert issue.comments == ("Keep the lockout.",)


@respx.mock
@pytest.mark.parametrize("status", [403, 404, 410])
def test_unreadable_comments_leave_the_issue_text_and_a_flag(client: GitHubClient, status: int) -> None:
    respx.get(f"{API}/repos/octo/app/issues/9").mock(
        return_value=httpx.Response(200, json={"title": "Login", "body": "Users sign in."})
    )
    respx.post(f"{API}/graphql").mock(return_value=httpx.Response(status, json={"message": "x"}))

    issue = client.issue(IssueRef("octo", "app", 9))

    assert issue is not None
    assert (issue.body, issue.comments, issue.comments_unreadable) == ("Users sign in.", (), True)


@respx.mock
def test_an_issue_graphql_cannot_resolve_leaves_a_flag(client: GitHubClient) -> None:
    respx.get(f"{API}/repos/octo/app/issues/9").mock(
        return_value=httpx.Response(200, json={"title": "Login", "body": ""})
    )
    errors = {"data": {"repository": {"issue": None}}, "errors": [{"type": "NOT_FOUND", "message": "gone"}]}
    respx.post(f"{API}/graphql").mock(return_value=httpx.Response(200, json=errors))

    issue = client.issue(IssueRef("octo", "app", 9))

    assert issue is not None
    assert issue.comments_unreadable is True


@respx.mock
def test_a_graphql_rate_limit_on_comments_still_fails(client: GitHubClient) -> None:
    respx.get(f"{API}/repos/octo/app/issues/9").mock(
        return_value=httpx.Response(200, json={"title": "Login", "body": ""})
    )
    limited = {"errors": [{"type": "RATE_LIMITED", "message": "API rate limit exceeded"}]}
    respx.post(f"{API}/graphql").mock(return_value=httpx.Response(200, json=limited))

    with pytest.raises(GitHubError, match="rate limit"):
        client.issue(IssueRef("octo", "app", 9))


def _moved(status: str, sha: str, name: str = "new.png", old: str = "old.png") -> dict[str, object]:
    return {"filename": name, "previous_filename": old, "status": status, "changes": 0, "sha": sha}


def _tree(truncated: bool = False) -> dict[str, object]:
    return {"truncated": truncated, "tree": [{"path": "old.png", "type": "blob", "sha": "same"}]}


@respx.mock
@pytest.mark.parametrize(
    ("status", "head_sha", "omitted", "changes"),
    [
        ("renamed", "same", False, 0),
        ("renamed", "edited", True, None),
        ("copied", "same", False, 0),
        ("copied", "edited", True, None),
    ],
)
def test_a_moved_file_is_compared_with_its_old_blob(
    client: GitHubClient, status: str, head_sha: str, omitted: bool, changes: int | None
) -> None:
    respx.get(f"{API}/repos/octo/app/pulls/5").mock(return_value=httpx.Response(200, json=PULL))
    respx.get(url__startswith=f"{API}/repos/octo/app/pulls/5/files").mock(
        return_value=httpx.Response(200, json=[_moved(status, head_sha)])
    )
    respx.get(f"{API}/repos/octo/app/git/trees/b1").mock(return_value=httpx.Response(200, json=_tree()))

    (moved,) = GitHubSource(client, "octo/app", 5).changed_files()

    assert (moved.patch_omitted, moved.changes) == (omitted, changes)


@respx.mock
def test_a_moved_file_with_no_sha_and_no_old_blob_gets_the_binary_note(client: GitHubClient) -> None:
    moved_file = _moved("renamed", "unused", old="gone.png")
    del moved_file["sha"]
    respx.get(f"{API}/repos/octo/app/pulls/5").mock(return_value=httpx.Response(200, json=PULL))
    respx.get(url__startswith=f"{API}/repos/octo/app/pulls/5/files").mock(
        return_value=httpx.Response(200, json=[moved_file])
    )
    respx.get(f"{API}/repos/octo/app/git/trees/b1").mock(return_value=httpx.Response(200, json=_tree()))

    (moved,) = GitHubSource(client, "octo/app", 5).changed_files()

    assert (moved.patch_omitted, moved.changes) == (True, None)


@respx.mock
def test_moving_many_files_costs_one_tree_read(client: GitHubClient) -> None:
    files = [_moved("renamed", "same", f"new/{n}.py", "old.png") for n in range(300)]
    respx.get(f"{API}/repos/octo/app/pulls/5").mock(return_value=httpx.Response(200, json=PULL))
    respx.get(url__startswith=f"{API}/repos/octo/app/pulls/5/files").mock(
        side_effect=lambda request: httpx.Response(
            200, json=files[(int(request.url.params["page"]) - 1) * 100 :][:100]
        )
    )
    tree = respx.get(f"{API}/repos/octo/app/git/trees/b1").mock(
        return_value=httpx.Response(200, json=_tree())
    )

    moved = GitHubSource(client, "octo/app", 5).changed_files()

    assert len(moved) == 300
    assert tree.call_count == 1


@respx.mock
def test_a_truncated_tree_falls_back_to_reading_the_one_blob(client: GitHubClient) -> None:
    respx.get(f"{API}/repos/octo/app/pulls/5").mock(return_value=httpx.Response(200, json=PULL))
    respx.get(url__startswith=f"{API}/repos/octo/app/pulls/5/files").mock(
        return_value=httpx.Response(200, json=[_moved("renamed", "same")])
    )
    respx.get(f"{API}/repos/octo/app/git/trees/b1").mock(
        return_value=httpx.Response(200, json={"truncated": True, "tree": []})
    )
    respx.get(f"{API}/repos/octo/app/contents/old.png").mock(
        return_value=httpx.Response(200, json={"sha": "same"})
    )

    (moved,) = GitHubSource(client, "octo/app", 5).changed_files()

    assert moved.patch_omitted is False


@respx.mock
def test_base_directories_are_listed_from_one_tree_read(client: GitHubClient) -> None:
    respx.get(f"{API}/repos/octo/app/pulls/5").mock(return_value=httpx.Response(200, json=PULL))
    entries = [
        {"path": "AGENTS.md", "type": "blob", "sha": "a"},
        {"path": "packages", "type": "tree", "sha": "t"},
        {"path": "packages/api/AGENTS.md", "type": "blob", "sha": "b"},
        {"path": "packages/api/ruff.toml", "type": "blob", "sha": "c"},
        {"path": "packages/api/src/app.py", "type": "blob", "sha": "d"},
    ]
    tree = respx.get(f"{API}/repos/octo/app/git/trees/b1").mock(
        return_value=httpx.Response(200, json={"truncated": False, "tree": entries})
    )
    source = GitHubSource(client, "octo/app", 5)

    assert source.list_base("packages/api") == {"AGENTS.md", "ruff.toml"}
    assert source.list_base("packages") == frozenset()
    assert source.list_base("missing") == frozenset()
    assert tree.call_count == 1


@respx.mock
def test_a_truncated_tree_lists_a_directory_through_the_contents_api(client: GitHubClient) -> None:
    respx.get(f"{API}/repos/octo/app/pulls/5").mock(return_value=httpx.Response(200, json=PULL))
    respx.get(f"{API}/repos/octo/app/git/trees/b1").mock(
        return_value=httpx.Response(200, json={"truncated": True, "tree": []})
    )
    listing = [
        {"name": "AGENTS.md", "type": "file", "path": "packages/api/AGENTS.md"},
        {"name": "src", "type": "dir", "path": "packages/api/src"},
    ]
    route = respx.get(f"{API}/repos/octo/app/contents/packages/api").mock(
        return_value=httpx.Response(200, json=listing)
    )
    respx.get(f"{API}/repos/octo/app/contents/gone").mock(return_value=httpx.Response(404, json={}))

    source = GitHubSource(client, "octo/app", 5)

    assert source.list_base("packages/api") == {"AGENTS.md"}
    assert route.calls[0].request.url.params["ref"] == "b1"
    assert source.list_base("gone") == frozenset()


@respx.mock
def test_a_maintainer_comment_behind_a_hundred_outsider_comments_is_still_read(client: GitHubClient) -> None:
    respx.get(f"{API}/repos/octo/app/issues/9").mock(
        return_value=httpx.Response(200, json={"title": "Login", "body": ""})
    )
    newest = {
        "pageInfo": {"hasPreviousPage": True, "startCursor": "c1"},
        "nodes": [_node("+1", "NONE") for _ in range(100)],
    }
    older = {
        "pageInfo": {"hasPreviousPage": False, "startCursor": None},
        "nodes": [_node("AC-3 is out of scope.", "OWNER")],
    }
    route = respx.post(f"{API}/graphql")
    route.side_effect = [
        httpx.Response(200, json={"data": {"repository": {"issue": {"comments": page}}}})
        for page in (newest, older)
    ]

    issue = client.issue(IssueRef("octo", "app", 9))

    assert issue is not None
    assert issue.comments == ("AC-3 is out of scope.",)
    assert json.loads(route.calls[1].request.content)["variables"]["before"] == "c1"
