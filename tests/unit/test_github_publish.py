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
    assert (summary.id, summary.body, summary.bot) == (2, "<!-- bylaw:summary --> real", True)


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
    assert (summary.id, summary.bot) == (3, True)


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


@respx.mock
def test_threads_carry_their_file(client: GitHubClient) -> None:
    bylaw = {"body": "x", "author": {"__typename": "Bot", "login": "b"}, "authorAssociation": "NONE"}
    thread = {"id": "T1", "isResolved": False, "path": "src/app.py", "comments": {"nodes": [bylaw]}}
    page = {"pageInfo": {"hasNextPage": False, "endCursor": None}, "nodes": [thread]}
    data = {"data": {"repository": {"pullRequest": {"author": {"login": "a"}, "reviewThreads": page}}}}
    respx.post(f"{API}/graphql").mock(return_value=httpx.Response(200, json=data))

    (read,) = client.review_threads("octo/app", 5)

    assert read.path == "src/app.py"


def _summary(comment_id: int, kind: str, login: str, association: str = "NONE") -> dict[str, object]:
    return {
        "id": comment_id,
        "body": f"<!-- bylaw:summary --> {login}",
        "user": {"type": kind, "login": login},
        "author_association": association,
    }


@respx.mock
def test_with_a_fixed_bot_login_only_that_bot_writes_the_summary() -> None:
    comments = [
        _summary(1, "Bot", "renovate[bot]"),
        _summary(2, "User", "owner", "OWNER"),
        _summary(3, "Bot", "bylaw-acme[bot]"),
    ]
    respx.get(url__startswith=f"{API}/repos/octo/app/issues/5/comments").mock(
        return_value=httpx.Response(200, json=comments)
    )

    with GitHubClient("t", bot_login="bylaw-acme[bot]") as client:
        summary = client.summary_comment("octo/app", 5)

    assert summary is not None
    assert (summary.id, summary.bot) == (3, True)


@respx.mock
def test_with_a_fixed_bot_login_a_summary_by_anyone_else_is_ignored() -> None:
    comments = [_summary(1, "Bot", "renovate[bot]"), _summary(2, "User", "owner", "OWNER")]
    respx.get(url__startswith=f"{API}/repos/octo/app/issues/5/comments").mock(
        return_value=httpx.Response(200, json=comments)
    )

    with GitHubClient("t", bot_login="bylaw-acme[bot]") as client:
        assert client.summary_comment("octo/app", 5) is None


@respx.mock
def test_with_a_fixed_bot_login_another_bot_s_thread_comment_is_not_trusted() -> None:
    def thread(thread_id: str, kind: str, login: str, association: str) -> dict[str, object]:
        comment = {
            "body": "x",
            "author": {"__typename": kind, "login": login},
            "authorAssociation": association,
        }
        return {"id": thread_id, "isResolved": False, "comments": {"nodes": [comment]}}

    # GraphQL names a bot without the [bot] suffix the REST API adds.
    nodes = [
        thread("T1", "Bot", "renovate", "NONE"),
        thread("T2", "Bot", "bylaw-acme", "NONE"),
        thread("T3", "User", "maintainer", "MEMBER"),
    ]
    respx.post(f"{API}/graphql").mock(return_value=httpx.Response(200, json=_threads_page(nodes, None)))

    with GitHubClient("t", bot_login="bylaw-acme[bot]") as client:
        threads = client.review_threads("octo/app", 5)

    assert [t.comments[0].trusted for t in threads] == [False, True, True]


@respx.mock
def test_an_installation_token_is_scoped_to_the_repositories_and_permissions_asked_for() -> None:
    route = respx.post(f"{API}/app/installations/7/access_tokens").mock(
        return_value=httpx.Response(
            201,
            json={
                "token": "ghs_scoped",
                "expires_at": "2026-10-18T13:00:00Z",
                "repositories": [{"id": 1, "full_name": "Acme/App"}],
            },
        )
    )

    with GitHubClient("jwt") as client:
        token = client.installation_token(7, ["app"], {"contents": "read"})

    assert token.token == "ghs_scoped"  # noqa: S105 - a fake token
    assert token.repositories == frozenset({"acme/app"})
    assert route.calls.last.request.headers["Authorization"] == "Bearer jwt"
    assert json.loads(route.calls.last.request.content) == {
        "repositories": ["app"],
        "permissions": {"contents": "read"},
    }


@respx.mock
def test_a_refused_installation_token_raises_with_its_status() -> None:
    respx.post(f"{API}/app/installations/7/access_tokens").mock(
        return_value=httpx.Response(422, json={"message": "not accessible to the installation"})
    )

    with GitHubClient("jwt") as client, pytest.raises(GitHubError) as raised:
        client.installation_token(7, [".github"], {"contents": "read"})

    assert raised.value.status == 422


@respx.mock
def test_the_app_login_is_its_slug_as_a_bot() -> None:
    respx.get(f"{API}/app").mock(return_value=httpx.Response(200, json={"id": 1, "slug": "bylaw-acme"}))

    with GitHubClient("jwt") as client:
        assert client.app_login() == "bylaw-acme[bot]"


@respx.mock
def test_a_file_on_the_default_branch_is_read_without_a_ref() -> None:
    route = respx.get(f"{API}/repos/acme/.github/contents/.bylaw.toml").mock(
        return_value=httpx.Response(200, content=b"max_comments = 3\n")
    )

    with GitHubClient("t") as client:
        assert client.file_text("acme/.github", ".bylaw.toml", None) == "max_comments = 3\n"

    assert "ref" not in route.calls.last.request.url.params


@respx.mock
def test_a_token_answer_that_names_no_repositories_names_none() -> None:
    respx.post(f"{API}/app/installations/7/access_tokens").mock(
        return_value=httpx.Response(201, json={"token": "ghs_any"})
    )

    with GitHubClient("jwt") as client:
        assert client.installation_token(7, ["app"], {"contents": "read"}).repositories == frozenset()


@respx.mock
def test_threads_carry_who_resolved_them_and_who_wrote_each_reply(client: GitHubClient) -> None:
    reply = {
        "body": "bylaw: ignore",
        "author": {"__typename": "User", "login": "carol"},
        "authorAssociation": "MEMBER",
    }
    thread = {"id": "T1", "isResolved": True, "resolvedBy": {"login": "dave"}, "comments": {"nodes": [reply]}}
    page = {"pageInfo": {"hasNextPage": False, "endCursor": None}, "nodes": [thread]}
    data = {"data": {"repository": {"pullRequest": {"author": {"login": "alice"}, "reviewThreads": page}}}}
    route = respx.post(f"{API}/graphql").mock(return_value=httpx.Response(200, json=data))

    threads = client.review_threads("octo/app", 5)

    assert (threads[0].resolved_by, threads[0].comments[0].author) == ("dave", "carol")
    assert "resolvedBy { login }" in route.calls[0].request.content.decode()
