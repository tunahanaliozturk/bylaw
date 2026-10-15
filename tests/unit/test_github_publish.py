import json
from collections.abc import Iterator

import httpx
import pytest
import respx

from bylaw.github import GitHubClient, ReviewComment

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
