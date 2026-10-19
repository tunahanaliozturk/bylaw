from collections.abc import Iterator

import httpx
import pytest
import respx

from bylaw.context import build_context
from bylaw.gitlab import GitLabClient, GitLabMergeRequest, closing_refs
from bylaw.requirements import extract_criteria
from bylaw.source import IssueRef

API = "https://gitlab.example.com/api/v4"
WEB = "https://gitlab.example.com"
P = f"{API}/projects/42"
OTHER = f"{API}/projects/group%2Fother"
APP = f"{API}/projects/group%2Fapp"
MR = {
    "iid": 5,
    "title": "Add parser",
    "description": "Closes #12",
    "author": {"id": 7},
    "references": {"full": "group/app!5"},
    "diff_refs": {"base_sha": "b1", "start_sha": "s1", "head_sha": "h1"},
}


def test_gitlabs_default_closing_pattern_names_every_issue_in_a_closing_statement() -> None:
    texts = [
        "Fix #20, Fixes #21 and Closes group/otherproject#22.",
        "This commit is also related to #17 and fixes #18, #19",
        "Implements issue #4 and resolving sub/deep/lib#5",
        f"Closing {WEB}/group/otherproject/-/issues/23.",
        "Closes sibling#6",
        "CLOSES #99, closes: #8, Closes #20 again",
        "closes ../..#7 and closes https://elsewhere.example/a/b/-/issues/9",
    ]

    refs = closing_refs(texts, "group/app", WEB)

    assert refs == (
        IssueRef("group", "app", 20),
        IssueRef("group", "app", 21),
        IssueRef("group", "otherproject", 22),
        IssueRef("group", "app", 18),
        IssueRef("group", "app", 19),
        IssueRef("group", "app", 4),
        IssueRef("sub", "deep/lib", 5),
        IssueRef("group", "otherproject", 23),
        IssueRef("group", "sibling", 6),
        IssueRef("group", "app", 8),
    )


def test_a_number_that_runs_into_letters_is_not_a_reference() -> None:
    assert closing_refs(["Closes #1abc and fixes #2_x"], "group/app", WEB) == ()


def test_an_issue_link_with_a_note_anchor_a_slash_or_a_query_is_recognised() -> None:
    texts = [
        f"Closes {WEB}/group/app/-/issues/7#note_1",
        f"Fixes {WEB}/group/app/-/issues/8/",
        f"Resolves {WEB}/group/app/-/issues/9?view=list",
        f"Closes {WEB}/group/app/-/issues/10abc",
    ]

    assert closing_refs(texts, "group/app", WEB) == (
        IssueRef("group", "app", 7),
        IssueRef("group", "app", 8),
        IssueRef("group", "app", 9),
    )


def test_a_nested_group_reference_keeps_its_full_path_in_the_label() -> None:
    (ref,) = closing_refs(["Fixes Org/Team/Lib#5"], "group/app", WEB)

    assert ref.label("group/app") == "org/team/lib#5"


def test_numbered_task_lists_count_and_inapplicable_tasks_do_not() -> None:
    criteria = extract_criteria("1. [ ] export as CSV\n2. [x] keep the header\n- [~] not for this release\n")

    assert [c.text for c in criteria] == ["export as CSV", "keep the header"]


@pytest.fixture
def client() -> Iterator[GitLabClient]:
    with GitLabClient("t", API) as gitlab:
        yield gitlab


@pytest.fixture
def server() -> Iterator[respx.MockRouter]:
    with respx.mock(assert_all_called=False) as router:
        router.get(f"{P}/merge_requests/5", name="mr").mock(return_value=httpx.Response(200, json=MR))
        router.get(f"{API}/user").mock(return_value=httpx.Response(200, json={"id": 99}))
        levels = {1: 40, 2: 20, 3: 30}

        def member(request: httpx.Request) -> httpx.Response:
            user = int(request.url.path.rsplit("/", 1)[1])
            if user not in levels:
                return httpx.Response(404, json={"message": "404 Not found"})
            return httpx.Response(200, json={"access_level": levels[user]})

        router.get(url__regex=r"/members/all/\d+$").mock(side_effect=member)
        yield router


def _mr(client: GitLabClient) -> GitLabMergeRequest:
    return GitLabMergeRequest(client, "42", 5)


def test_closing_issues_come_from_gitlab_and_from_the_title_description_and_commits(
    client: GitLabClient, server: respx.MockRouter
) -> None:
    server["mr"].return_value = httpx.Response(200, json={**MR, "title": "Implement export, closes #15"})
    server.get(url__startswith=f"{P}/merge_requests/5/closes_issues").mock(
        return_value=httpx.Response(
            200, json=[{"iid": 3, "references": {"full": "Group/Other#3"}}, {"id": 1}]
        )
    )
    server.get(url__startswith=f"{P}/merge_requests/5/commits").mock(
        return_value=httpx.Response(200, json=[{"message": "Resolves #12\n\nFixes #14"}])
    )

    refs = _mr(client).closing_issue_refs()

    assert refs == (
        IssueRef("group", "other", 3),
        IssueRef("group", "app", 15),
        IssueRef("group", "app", 12),
        IssueRef("group", "app", 14),
    )


def test_an_issue_brings_its_description_and_only_developers_public_comments(
    client: GitLabClient, server: respx.MockRouter
) -> None:
    server.get(f"{OTHER}/issues/3").mock(
        return_value=httpx.Response(200, json={"iid": 3, "title": "Export", "description": "- [ ] CSV"})
    )
    notes = [  # newest first, as asked for
        {"id": 14, "body": "newest word", "author": {"id": 1}},
        {"id": 13, "body": "internal note", "author": {"id": 1}, "internal": True},
        {"id": 12, "body": "changed the title", "author": {"id": 1}, "system": True},
        {"id": 11, "body": "rescope it", "author": {"id": 2}},
        {"id": 10, "body": "from outside", "author": {"id": 50}},
        {"id": 9, "body": "first word", "author": {"id": 3}},
    ]
    route = server.get(url__startswith=f"{OTHER}/issues/3/notes").mock(
        return_value=httpx.Response(200, json=notes)
    )

    issue = _mr(client).read_issue(IssueRef("group", "other", 3))

    assert issue is not None
    assert (issue.title, issue.body, issue.comments) == ("Export", "- [ ] CSV", ("first word", "newest word"))
    assert route.calls.last.request.url.params["sort"] == "desc"


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(404, json={"message": "404 Not found"}),
        httpx.Response(403, json={"message": "403 Forbidden"}),
        httpx.Response(200, json={"iid": 3, "title": "Secret", "description": "x", "confidential": True}),
    ],
)
def test_a_missing_hidden_or_confidential_issue_is_left_out(
    client: GitLabClient, server: respx.MockRouter, response: httpx.Response
) -> None:
    server.get(f"{OTHER}/issues/3").mock(return_value=response)

    assert _mr(client).read_issue(IssueRef("group", "other", 3)) is None


def test_comments_that_cannot_be_read_are_flagged(client: GitLabClient, server: respx.MockRouter) -> None:
    server.get(f"{OTHER}/issues/3").mock(
        return_value=httpx.Response(200, json={"iid": 3, "title": "Export", "description": ""})
    )
    server.get(url__startswith=f"{OTHER}/issues/3/notes").mock(
        return_value=httpx.Response(403, json={"message": "403 Forbidden"})
    )

    issue = _mr(client).read_issue(IssueRef("group", "other", 3))

    assert issue is not None
    assert (issue.comments, issue.comments_unreadable) == ((), True)


def test_an_issue_in_an_unlisted_project_is_not_read(client: GitLabClient, server: respx.MockRouter) -> None:
    server.get(url__startswith=f"{P}/merge_requests/5/commits").mock(
        return_value=httpx.Response(200, json=[])
    )
    server.get(url__startswith=f"{P}/merge_requests/5/diffs").mock(return_value=httpx.Response(200, json=[]))
    server.get(url__startswith=f"{P}/merge_requests/5/closes_issues").mock(
        return_value=httpx.Response(200, json=[{"iid": 3, "references": {"full": "group/other#3"}}])
    )
    server.get(url__startswith=f"{P}/repository/").mock(return_value=httpx.Response(404, json={}))
    server.get(f"{APP}/issues/12").mock(
        return_value=httpx.Response(200, json={"iid": 12, "title": "Parser", "description": "- [ ] parse"})
    )
    server.get(url__startswith=f"{APP}/issues/12/notes").mock(return_value=httpx.Response(200, json=[]))
    other = server.get(url__startswith=f"{OTHER}/issues/3")

    context = build_context(_mr(client), env={})

    assert [r.source for r in context.requirements] == ["issue#12"]
    assert (
        "`group/other#3` is in another repository; list it under issue_repos in .bylaw.toml to use it."
        in (context.notes)
    )
    assert not other.called
