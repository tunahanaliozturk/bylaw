from collections.abc import Iterator

import httpx
import pytest
import respx

from bylaw.github import GitHubClient, GitHubError, GitHubSource
from bylaw.source import IssueRef

API = "https://api.github.com"
TOKEN = "ghp_secret_token"  # noqa: S105 - a fake token the error message must not echo
PULL = {"title": "Add parser", "body": "Closes #12", "base": {"sha": "b1"}, "head": {"sha": "h1"}}


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
        return_value=httpx.Response(200, json=[{"filename": "big.json", "status": "modified"}])
    )

    files = GitHubSource(client, "octo/app", 5).changed_files()

    assert files[0].patch_omitted is True


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
