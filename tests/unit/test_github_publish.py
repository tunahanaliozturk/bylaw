import json
from collections.abc import Iterator

import httpx
import pytest
import respx

from bylaw.github import GitHubClient, GitHubError, ReviewComment

API = "https://api.github.com"


@pytest.fixture
def client() -> Iterator[GitHubClient]:
    with GitHubClient("t") as github:
        yield github


def _thread(thread_id: str, body: str, typename: str, association: str) -> dict[str, object]:
    comment = {"body": body, "author": {"__typename": typename}, "authorAssociation": association}
    return {"id": thread_id, "isResolved": False, "comments": {"nodes": [comment]}}


def _threads_page(nodes: list[dict[str, object]], next_cursor: str | None) -> dict[str, object]:
    page_info = {"hasNextPage": next_cursor is not None, "endCursor": next_cursor}
    threads = {"pageInfo": page_info, "nodes": nodes}
    return {"data": {"repository": {"pullRequest": {"reviewThreads": threads}}}}


@respx.mock
def test_review_threads_are_read_across_pages_with_trust(client: GitHubClient) -> None:
    pages = [
        _threads_page([_thread("T1", "a", "Bot", "NONE")], "c1"),
        _threads_page([_thread("T2", "b", "User", "CONTRIBUTOR")], None),
    ]
    respx.post(f"{API}/graphql").mock(side_effect=[httpx.Response(200, json=page) for page in pages])

    threads = client.review_threads("octo/app", 5)

    assert [(t.id, t.comments[0].trusted) for t in threads] == [("T1", True), ("T2", False)]


@respx.mock
def test_the_summary_is_the_first_trusted_comment_with_the_marker(client: GitHubClient) -> None:
    comments = [
        {
            "id": 1,
            "body": "<!-- bylaw:summary --> forged",
            "user": {"type": "User"},
            "author_association": "NONE",
        },
        {
            "id": 2,
            "body": "<!-- bylaw:summary --> real",
            "user": {"type": "Bot"},
            "author_association": "NONE",
        },
    ]
    respx.get(url__startswith=f"{API}/repos/octo/app/issues/5/comments").mock(
        return_value=httpx.Response(200, json=comments)
    )

    summary = client.summary_comment("octo/app", 5)

    assert summary is not None
    assert (summary.id, summary.body) == (2, "<!-- bylaw:summary --> real")


@respx.mock
def test_upsert_edits_an_existing_summary_and_creates_a_missing_one(client: GitHubClient) -> None:
    edit = respx.patch(f"{API}/repos/octo/app/issues/comments/2").mock(
        return_value=httpx.Response(200, json={})
    )
    create = respx.post(f"{API}/repos/octo/app/issues/5/comments").mock(
        return_value=httpx.Response(201, json={})
    )

    client.upsert_summary("octo/app", 5, 2, "body one")
    client.upsert_summary("octo/app", 5, None, "body two")

    assert json.loads(edit.calls.last.request.content) == {"body": "body one"}
    assert json.loads(create.calls.last.request.content) == {"body": "body two"}


@respx.mock
def test_a_review_is_one_comment_event_with_multi_line_ranges(client: GitHubClient) -> None:
    route = respx.post(f"{API}/repos/octo/app/pulls/5/reviews").mock(
        return_value=httpx.Response(200, json={})
    )

    client.create_review(
        "octo/app",
        5,
        "h1",
        "bylaw left 2 new comments.",
        [ReviewComment("a.py", 3, 3, "one"), ReviewComment("b.py", 9, 7, "two")],
    )

    assert json.loads(route.calls.last.request.content) == {
        "commit_id": "h1",
        "event": "COMMENT",
        "body": "bylaw left 2 new comments.",
        "comments": [
            {"path": "a.py", "line": 3, "side": "RIGHT", "body": "one"},
            {
                "path": "b.py",
                "line": 9,
                "side": "RIGHT",
                "body": "two",
                "start_line": 7,
                "start_side": "RIGHT",
            },
        ],
    }


@respx.mock
def test_threads_are_resolved_and_reopened_with_mutations(client: GitHubClient) -> None:
    route = respx.post(f"{API}/graphql").mock(return_value=httpx.Response(200, json={"data": {}}))

    client.set_thread_resolved("T1", resolved=True)
    client.set_thread_resolved("T1", resolved=False)

    sent = [json.loads(call.request.content) for call in route.calls]
    # "unresolveReviewThread" contains "resolveReviewThread", so check the opening of each mutation.
    assert ["{ resolveReviewThread(" in s["query"] for s in sent] == [True, False]
    assert ["{ unresolveReviewThread(" in s["query"] for s in sent] == [False, True]
    assert all(s["variables"] == {"id": "T1"} for s in sent)


@respx.mock
def test_the_summary_marker_must_open_the_comment_and_bots_come_first(client: GitHubClient) -> None:
    comments = [
        {
            "id": 1,
            "body": "see <!-- bylaw:summary --> here",
            "user": {"type": "User"},
            "author_association": "OWNER",
        },
        {
            "id": 2,
            "body": "<!-- bylaw:summary --> by hand",
            "user": {"type": "User"},
            "author_association": "OWNER",
        },
        {
            "id": 3,
            "body": "<!-- bylaw:summary --> bot",
            "user": {"type": "Bot"},
            "author_association": "NONE",
        },
    ]
    respx.get(url__startswith=f"{API}/repos/octo/app/issues/5/comments").mock(
        return_value=httpx.Response(200, json=comments)
    )

    summary = client.summary_comment("octo/app", 5)

    assert summary is not None
    assert summary.id == 3


@respx.mock
def test_replies_by_the_pull_request_author_are_marked(client: GitHubClient) -> None:
    reply = {
        "body": "bylaw: ignore",
        "author": {"__typename": "User", "login": "alice"},
        "authorAssociation": "MEMBER",
    }
    thread = {"id": "T1", "isResolved": False, "comments": {"nodes": [reply]}}
    page = {"pageInfo": {"hasNextPage": False, "endCursor": None}, "nodes": [thread]}
    data = {"data": {"repository": {"pullRequest": {"author": {"login": "alice"}, "reviewThreads": page}}}}
    respx.post(f"{API}/graphql").mock(return_value=httpx.Response(200, json=data))

    threads = client.review_threads("octo/app", 5)

    assert threads[0].comments[0].by_pr_author is True


@respx.mock
def test_a_late_reply_in_a_long_thread_is_read(client: GitHubClient) -> None:
    def comment(cid: str, body: str, typename: str, association: str) -> dict[str, object]:
        return {"id": cid, "body": body, "author": {"__typename": typename}, "authorAssociation": association}

    first = comment("C0", "finding", "Bot", "NONE")
    recent = [comment(f"C{n}", f"reply {n}", "User", "NONE") for n in range(31, 80)]
    recent.append(comment("C80", "bylaw: ignore, accepted risk", "User", "OWNER"))
    thread = {"id": "T1", "isResolved": False, "comments": {"nodes": [first]}, "recent": {"nodes": recent}}
    respx.post(f"{API}/graphql").mock(return_value=httpx.Response(200, json=_threads_page([thread], None)))

    (read,) = client.review_threads("octo/app", 5)

    assert read.comments[0].body == "finding"
    assert read.comments[-1].body == "bylaw: ignore, accepted risk"
    assert len(read.comments) == 51


@respx.mock
def test_a_short_thread_is_not_read_twice(client: GitHubClient) -> None:
    only = {"id": "C0", "body": "finding", "author": {"__typename": "Bot"}, "authorAssociation": "NONE"}
    thread = {"id": "T1", "isResolved": False, "comments": {"nodes": [only]}, "recent": {"nodes": [only]}}
    respx.post(f"{API}/graphql").mock(return_value=httpx.Response(200, json=_threads_page([thread], None)))

    (read,) = client.review_threads("octo/app", 5)

    assert len(read.comments) == 1


@respx.mock
def test_threads_carry_their_current_and_original_lines(client: GitHubClient) -> None:
    thread = _thread("T1", "a", "Bot", "NONE") | {"line": None, "originalLine": 7}
    respx.post(f"{API}/graphql").mock(return_value=httpx.Response(200, json=_threads_page([thread], None)))

    (read,) = client.review_threads("octo/app", 5)

    assert (read.line, read.original_line) == (None, 7)


def _long_thread() -> dict[str, object]:
    first = {"id": "C0", "body": "finding", "author": {"__typename": "Bot"}, "authorAssociation": "NONE"}
    reply = {"id": "C150", "body": "newest", "author": {"__typename": "User"}, "authorAssociation": "NONE"}
    newest = {"pageInfo": {"hasPreviousPage": True, "startCursor": "older"}, "nodes": [reply]}
    return {"id": "T1", "isResolved": False, "comments": {"nodes": [first]}, "recent": newest}


@respx.mock
def test_a_graphql_error_on_older_replies_reads_the_thread_without_them(client: GitHubClient) -> None:
    respx.post(f"{API}/graphql").side_effect = [
        httpx.Response(200, json=_threads_page([_long_thread()], None)),
        httpx.Response(200, json={"errors": [{"type": "INTERNAL", "message": "Something went wrong"}]}),
    ]

    (read,) = client.review_threads("octo/app", 5)

    assert [c.body for c in read.comments] == ["finding", "newest"]
    assert read.older_replies_unread is True


@respx.mock
def test_a_rate_limit_on_older_replies_still_fails(client: GitHubClient) -> None:
    limited = {"errors": [{"type": "RATE_LIMITED", "message": "API rate limit exceeded"}]}
    respx.post(f"{API}/graphql").side_effect = [
        httpx.Response(200, json=_threads_page([_long_thread()], None)),
        httpx.Response(200, json=limited),
    ]

    with pytest.raises(GitHubError, match="rate limit"):
        client.review_threads("octo/app", 5)


@respx.mock
def test_replies_in_the_middle_of_a_very_long_thread_are_read(client: GitHubClient) -> None:
    def comment(cid: int, body: str, association: str = "NONE") -> dict[str, object]:
        return {
            "id": f"C{cid}",
            "body": body,
            "author": {"__typename": "User"},
            "authorAssociation": association,
        }

    first = {"id": "C0", "body": "finding", "author": {"__typename": "Bot"}, "authorAssociation": "NONE"}
    newest = {
        "pageInfo": {"hasPreviousPage": True, "startCursor": "older"},
        "nodes": [comment(n, f"reply {n}") for n in range(101, 201)],
    }
    thread = {"id": "T1", "isResolved": False, "comments": {"nodes": [first]}, "recent": newest}
    older = {
        "data": {
            "node": {
                "comments": {
                    "pageInfo": {"hasPreviousPage": False, "startCursor": None},
                    "nodes": [first, comment(1, "bylaw: ignore, accepted", "OWNER")]
                    + [comment(n, f"reply {n}") for n in range(2, 101)],
                }
            }
        }
    }
    route = respx.post(f"{API}/graphql")
    route.side_effect = [
        httpx.Response(200, json=_threads_page([thread], None)),
        httpx.Response(200, json=older),
    ]

    (read,) = client.review_threads("octo/app", 5)

    bodies = [c.body for c in read.comments]
    assert bodies[0] == "finding"
    assert "bylaw: ignore, accepted" in bodies
    assert len(bodies) == 201
    assert json.loads(route.calls[1].request.content)["variables"]["before"] == "older"
