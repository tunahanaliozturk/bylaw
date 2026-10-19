import hashlib
import json
from collections.abc import Iterator

import httpx
import pytest
import respx

from bylaw.config import Config
from bylaw.github import ReviewComment
from bylaw.gitlab import GitLabClient, GitLabMergeRequest
from bylaw.model import Category, ChangedFile, Finding, ReviewContext, ReviewResult, Severity
from bylaw.plan import Group, added_text, group_findings
from bylaw.publish import publish
from bylaw.render import SUMMARY_MARKER, inline_body, inline_parts, read_state

API = "https://gitlab.example.com/api/v4"
P = f"{API}/projects/42"
MR = {
    "iid": 5,
    "title": "Add parser",
    "author": {"id": 7, "username": "dev"},
    "references": {"full": "group/app!5"},
    "diff_refs": {"base_sha": "b1", "start_sha": "s1", "head_sha": "h1"},
}
BOT, MAINTAINER, REPORTER, AUTHOR = 99, 40, 20, 7
LEVELS = {BOT: 30, MAINTAINER: 40, REPORTER: 20, AUTHOR: 30}
APP_PATCH = "@@ -3,2 +3,5 @@\n ctx\n+one\n+two\n+three\n ctx2\n"
DIFFS: list[dict[str, object]] = [
    {"old_path": "app.py", "new_path": "app.py", "diff": APP_PATCH},
    {"old_path": "old.py", "new_path": "new.py", "renamed_file": True, "diff": "@@ -1 +1 @@\n-a\n+b\n"},
]


@pytest.fixture
def client() -> Iterator[GitLabClient]:
    with GitLabClient("t", API) as gitlab:
        yield gitlab


@pytest.fixture
def server() -> Iterator[respx.MockRouter]:
    with respx.mock(assert_all_called=False) as router:
        router.get(f"{P}/merge_requests/5").mock(return_value=httpx.Response(200, json=MR))
        router.get(f"{API}/user").mock(return_value=httpx.Response(200, json={"id": BOT, "username": "bot"}))
        router.get(url__startswith=f"{P}/merge_requests/5/diffs").mock(
            return_value=httpx.Response(200, json=DIFFS)
        )
        router.get(url__regex=rf"{P}/members/all/\d+$").mock(side_effect=_member)
        yield router


def _member(request: httpx.Request) -> httpx.Response:
    user = int(request.url.path.rsplit("/", 1)[1])
    if user not in LEVELS:
        return httpx.Response(404, json={"message": "404 Not found"})
    return httpx.Response(200, json={"id": user, "access_level": LEVELS[user]})


def _note(note_id: int, body: str, author: int, **extra: object) -> dict[str, object]:
    return {"id": note_id, "body": body, "author": {"id": author}, "system": False, **extra}


def _mr(client: GitLabClient) -> GitLabMergeRequest:
    return GitLabMergeRequest(client, "42", 5)


def _rendered(  # noqa: PLR0913 - a finding's parts, each a distinct input
    path: str,
    line: int,
    start: int,
    *,
    message: str = "m",
    suggestion: str | None = None,
    others: tuple[str, ...] = (),
) -> ReviewComment:
    """A comment as publish() builds it, from a rendered finding."""

    def finding(file: str) -> Finding:
        return Finding(
            file=file,
            line_start=start,
            line_end=line,
            category=Category.BUG,
            severity=Severity.HIGH,
            message=message,
            suggestion=suggestion,
        )

    group = Group(finding=finding(path), fingerprint="0123456789abcdef", others=tuple(map(finding, others)))
    return ReviewComment(path, line, start, inline_body(group), inline_parts(group))


def _quick_actions(body: str) -> list[str]:
    """Lines GitLab would run, read as its extractor does: carriage returns deleted first, then every
    line that starts with a slash outside a fenced code block."""
    found: list[str] = []
    fence: str | None = None
    for line in body.replace("\r", "").split("\n"):
        if fence is None and line.startswith(("```", "~~~")):
            fence = line[: len(line) - len(line.lstrip(line[0]))]
        elif (
            fence is not None
            and line.strip()
            and set(line.strip()) == {fence[0]}
            and len(line.strip()) >= len(fence)
        ):
            fence = None
        elif fence is None and line.startswith("/"):
            found.append(line)
    return found


def test_threads_carry_trust_by_role_and_bylaws_own_account(
    client: GitLabClient, server: respx.MockRouter
) -> None:
    position = {"new_path": "app.py", "new_line": 4, "head_sha": "h1"}
    discussions = [
        {
            "id": "d1",
            "individual_note": False,
            "notes": [
                _note(1, "finding", BOT, type="DiffNote", position=position, resolvable=True, resolved=False),
                _note(2, "bylaw: ignore", REPORTER, type="DiffNote", resolvable=True, resolved=False),
                _note(3, "bylaw: ignore", AUTHOR, type="DiffNote", resolvable=True, resolved=False),
                _note(4, "changed the line", 1, system=True),
            ],
        },
        {"id": "d2", "individual_note": True, "notes": [_note(5, "plain comment", MAINTAINER)]},
    ]
    server.get(url__startswith=f"{P}/merge_requests/5/discussions").mock(
        return_value=httpx.Response(200, json=discussions)
    )

    threads = _mr(client).review_threads("group/app", 5)

    assert len(threads) == 1
    thread = threads[0]
    assert (thread.id, thread.resolved, thread.path, thread.line, thread.original_line) == (
        "d1",
        False,
        "app.py",
        4,
        4,
    )
    assert [(c.trusted, c.by_pr_author) for c in thread.comments] == [
        (True, False),
        (False, False),
        (True, True),
    ]


def test_a_thread_left_on_an_older_head_is_outdated_and_a_fully_resolved_one_is_resolved(
    client: GitLabClient, server: respx.MockRouter
) -> None:
    position = {"new_path": "app.py", "new_line": 9, "head_sha": "old"}
    note = _note(1, "f", BOT, type="DiffNote", position=position, resolvable=True, resolved=True)
    server.get(url__startswith=f"{P}/merge_requests/5/discussions").mock(
        return_value=httpx.Response(200, json=[{"id": "d1", "notes": [note]}])
    )

    thread = _mr(client).review_threads("group/app", 5)[0]

    assert (thread.resolved, thread.line, thread.original_line) == (True, None, 9)


def test_the_summary_is_bylaws_own_note_first_then_a_developers(
    client: GitLabClient, server: respx.MockRouter
) -> None:
    notes = [
        _note(1, f"{SUMMARY_MARKER} forged", REPORTER),
        _note(2, f"{SUMMARY_MARKER} by hand", MAINTAINER),
        _note(3, f"quoting {SUMMARY_MARKER}", BOT),
        _note(4, f"{SUMMARY_MARKER} real", BOT),
    ]
    server.get(url__startswith=f"{P}/merge_requests/5/notes").mock(
        return_value=httpx.Response(200, json=notes)
    )

    summary = _mr(client).summary_comment("group/app", 5)

    assert summary is not None
    assert (summary.id, summary.bot) == (4, True)


def test_once_bylaw_knows_its_account_a_persons_marker_note_is_never_its_summary(
    client: GitLabClient, server: respx.MockRouter
) -> None:
    server.get(url__startswith=f"{P}/merge_requests/5/notes").mock(
        return_value=httpx.Response(200, json=[_note(2, f"{SUMMARY_MARKER} by hand", MAINTAINER)])
    )

    assert _mr(client).summary_comment("group/app", 5) is None


def test_a_first_run_posts_its_own_summary_and_leaves_a_persons_note_alone(
    client: GitLabClient, server: respx.MockRouter
) -> None:
    context = ReviewContext(
        base_sha="s1", head_sha="h1", title="t", files=(), rules=(), requirements=(), findings=(), notes=()
    )
    server.get(url__startswith=f"{P}/merge_requests/5/discussions").mock(
        return_value=httpx.Response(200, json=[])
    )
    server.get(url__startswith=f"{P}/merge_requests/5/notes").mock(
        return_value=httpx.Response(200, json=[_note(2, f"{SUMMARY_MARKER} by hand", MAINTAINER)])
    )
    edit = server.put(f"{P}/merge_requests/5/notes/2").mock(return_value=httpx.Response(200, json={}))
    create = server.post(f"{P}/merge_requests/5/notes").mock(return_value=httpx.Response(201, json={}))

    publish(_mr(client), "group/app", 5, context=context, result=ReviewResult(), config=Config())

    assert (create.called, edit.called) == (True, False)


def test_without_its_own_identity_bylaw_trusts_no_summary_as_its_own(
    client: GitLabClient, server: respx.MockRouter
) -> None:
    server.get(f"{API}/user").mock(return_value=httpx.Response(403, json={"message": "403 Forbidden"}))
    server.get(url__startswith=f"{P}/merge_requests/5/notes").mock(
        return_value=httpx.Response(200, json=[_note(4, f"{SUMMARY_MARKER} real", BOT)])
    )

    summary = _mr(client).summary_comment("group/app", 5)

    assert summary is not None
    assert summary.bot is False  # a Developer-role note still carries mutes, never the review memory


def test_the_summary_is_edited_in_place_or_created(client: GitLabClient, server: respx.MockRouter) -> None:
    edit = server.put(f"{P}/merge_requests/5/notes/2").mock(return_value=httpx.Response(200, json={}))
    create = server.post(f"{P}/merge_requests/5/notes").mock(return_value=httpx.Response(201, json={}))
    mr = _mr(client)

    mr.upsert_summary("group/app", 5, 2, "one")
    mr.upsert_summary("group/app", 5, None, "two")

    assert json.loads(edit.calls.last.request.content) == {"body": "one"}
    assert json.loads(create.calls.last.request.content) == {"body": "two"}


def test_a_line_that_could_run_a_quick_action_is_made_inert(
    client: GitLabClient, server: respx.MockRouter
) -> None:
    create = server.post(f"{P}/merge_requests/5/notes").mock(return_value=httpx.Response(201, json={}))

    _mr(client).upsert_summary("group/app", 5, None, "text\n/merge\n/approve now\n  /label ~x")

    body = json.loads(create.calls.last.request.content)["body"]
    assert body == "text\n&#8203;/merge\n&#8203;/approve now\n  /label ~x"


def test_a_carriage_return_cannot_carry_a_quick_action_past_the_guard(
    client: GitLabClient, server: respx.MockRouter
) -> None:
    create = server.post(f"{P}/merge_requests/5/notes").mock(return_value=httpx.Response(201, json={}))

    # GitLab deletes every carriage return before it looks for quick actions.
    _mr(client).upsert_summary("group/app", 5, None, "Looks fine.\n\r/approve\n\r/merge")

    assert _quick_actions(json.loads(create.calls.last.request.content)["body"]) == []


def test_a_carriage_return_cannot_close_the_suggestion_early(
    client: GitLabClient, server: respx.MockRouter
) -> None:
    create = server.post(f"{P}/merge_requests/5/discussions").mock(return_value=httpx.Response(201, json={}))
    comment = _rendered("new.py", 1, 1, message="m\r\n\r/close", suggestion="x``\r`\n/merge\nafter")

    _mr(client).create_review("group/app", 5, "h1", "", [comment])

    sent = json.loads(create.calls.last.request.content)["body"]
    assert _quick_actions(sent) == []
    assert "````suggestion\nx```\n/merge\nafter\n````" in sent


def test_a_single_line_comment_is_a_discussion_on_the_new_line(
    client: GitLabClient, server: respx.MockRouter
) -> None:
    create = server.post(f"{P}/merge_requests/5/discussions").mock(return_value=httpx.Response(201, json={}))

    _mr(client).create_review("group/app", 5, "h1", "ignored", [ReviewComment("new.py", 1, 1, "body")])

    sent = json.loads(create.calls.last.request.content)
    assert sent == {
        "body": "body",
        "position": {
            "position_type": "text",
            "base_sha": "b1",
            "start_sha": "s1",
            "head_sha": "h1",
            "old_path": "old.py",
            "new_path": "new.py",
            "new_line": 1,
        },
    }


def test_a_multi_line_comment_has_a_line_range_and_its_suggestion_covers_it(
    client: GitLabClient, server: respx.MockRouter
) -> None:
    create = server.post(f"{P}/merge_requests/5/discussions").mock(return_value=httpx.Response(201, json={}))

    _mr(client).create_review("group/app", 5, "h1", "", [_rendered("app.py", 6, 4, suggestion="fixed")])

    sent = json.loads(create.calls.last.request.content)
    sha = hashlib.sha1(b"app.py").hexdigest()  # noqa: S324 - GitLab's line code format, not security
    # Added lines keep the old line counter where they were inserted: 3 is context, 4 to 6 are added.
    assert sent["position"]["line_range"] == {
        "start": {"line_code": f"{sha}_4_4", "type": "new", "new_line": 4},
        "end": {"line_code": f"{sha}_4_6", "type": "new", "new_line": 6},
    }
    assert sent["position"]["new_line"] == 6
    assert "```suggestion:-2+0\nfixed\n```" in sent["body"]


def test_a_position_gitlab_refuses_becomes_a_discussion_that_names_the_line(
    client: GitLabClient, server: respx.MockRouter
) -> None:
    def serve(request: httpx.Request) -> httpx.Response:
        if "position" in json.loads(request.content):
            return httpx.Response(400, json={"message": '400 Bad request - Note {:line_code=>["invalid"]}'})
        return httpx.Response(201, json={})

    create = server.post(f"{P}/merge_requests/5/discussions").mock(side_effect=serve)

    _mr(client).create_review("group/app", 5, "h1", "", [_rendered("new.py", 1, 1)])

    sent = json.loads(create.calls.last.request.content)
    assert "position" not in sent
    assert sent["body"].startswith("On `new.py:1`")
    assert "<!-- bylaw:fp=0123456789abcdef -->" in sent["body"]


def test_the_line_named_in_an_unpositioned_discussion_cannot_run_a_quick_action(
    client: GitLabClient, server: respx.MockRouter
) -> None:
    def serve(request: httpx.Request) -> httpx.Response:
        if "position" in json.loads(request.content):
            return httpx.Response(400, json={"message": "400 Bad request"})
        return httpx.Response(201, json={})

    create = server.post(f"{P}/merge_requests/5/discussions").mock(side_effect=serve)

    _mr(client).create_review("group/app", 5, "h1", "", [_rendered("odd\r\n/merge.py", 1, 1)])

    assert _quick_actions(json.loads(create.calls.last.request.content)["body"]) == []


def test_a_rejected_line_range_falls_back_to_a_single_line(
    client: GitLabClient, server: respx.MockRouter
) -> None:
    def serve(request: httpx.Request) -> httpx.Response:
        if "line_range" in json.loads(request.content)["position"]:
            return httpx.Response(400, json={"message": '400 Bad request - Note {:line_code=>["invalid"]}'})
        return httpx.Response(201, json={})

    create = server.post(f"{P}/merge_requests/5/discussions").mock(side_effect=serve)

    _mr(client).create_review("group/app", 5, "h1", "", [ReviewComment("app.py", 6, 4, "b")])

    assert len(create.calls) == 2
    assert "line_range" not in json.loads(create.calls.last.request.content)["position"]


def test_suggestion_lines_are_left_as_written_and_prose_lines_made_inert(
    client: GitLabClient, server: respx.MockRouter
) -> None:
    create = server.post(f"{P}/merge_requests/5/discussions").mock(return_value=httpx.Response(201, json={}))
    comment = _rendered("new.py", 1, 1, message="m\n/close", suggestion="/usr/bin/env")

    _mr(client).create_review("group/app", 5, "h1", "", [comment])

    sent = json.loads(create.calls.last.request.content)["body"]
    assert "\n&#8203;/close\n" in sent
    assert "```suggestion\n/usr/bin/env\n```" in sent


def test_a_path_with_a_line_break_keeps_the_suggestion_whole_and_its_range(
    client: GitLabClient, server: respx.MockRouter
) -> None:
    create = server.post(f"{P}/merge_requests/5/discussions").mock(return_value=httpx.Response(201, json={}))
    comment = _rendered("app.py", 6, 4, suggestion="/fixed", others=("odd\n/merge.py",))

    _mr(client).create_review("group/app", 5, "h1", "", [comment])

    sent = json.loads(create.calls.last.request.content)["body"]
    assert "```suggestion:-2+0\n/fixed\n```" in sent
    assert _quick_actions(sent) == []


def test_threads_are_resolved_and_reopened(client: GitLabClient, server: respx.MockRouter) -> None:
    route = server.put(f"{P}/merge_requests/5/discussions/d1").mock(return_value=httpx.Response(200, json={}))
    mr = _mr(client)

    mr.set_thread_resolved("d1", resolved=True)
    mr.set_thread_resolved("d1", resolved=False)

    assert [c.request.url.params["resolved"] for c in route.calls] == ["true", "false"]


def test_a_rerun_resolves_the_discussion_of_a_fixed_finding(
    client: GitLabClient, server: respx.MockRouter
) -> None:
    finding = Finding(
        file="app.py",
        line_start=4,
        line_end=4,
        category=Category.BUG,
        severity=Severity.HIGH,
        message="off by one",
    )
    context = ReviewContext(
        base_sha="s1",
        head_sha="h1",
        title="t",
        files=(ChangedFile(path="app.py", status="modified", patch=APP_PATCH),),
        rules=(),
        requirements=(),
        findings=(),
        notes=(),
    )
    fp = group_findings([finding], added_text(context))[0].fingerprint
    position = {"new_path": "app.py", "new_line": 4, "head_sha": "h1"}
    first = _note(
        1, f"old\n\n<!-- bylaw:fp={fp} -->", BOT, type="DiffNote", position=position, resolvable=True
    )
    server.get(url__startswith=f"{P}/merge_requests/5/discussions").mock(
        return_value=httpx.Response(200, json=[{"id": "d1", "notes": [first]}])
    )
    server.get(url__startswith=f"{P}/merge_requests/5/notes").mock(return_value=httpx.Response(200, json=[]))
    resolve = server.put(f"{P}/merge_requests/5/discussions/d1").mock(
        return_value=httpx.Response(200, json={})
    )
    summary = server.post(f"{P}/merge_requests/5/notes").mock(return_value=httpx.Response(201, json={}))

    plan = publish(_mr(client), "group/app", 5, context=context, result=ReviewResult(), config=Config())

    assert plan.resolve == ("d1",)
    assert resolve.calls.last.request.url.params["resolved"] == "true"
    body = json.loads(summary.calls.last.request.content)["body"]
    assert body.startswith(SUMMARY_MARKER)
    assert read_state(body).auto_resolved == frozenset({"d1"})


def test_a_resolved_thread_names_who_resolved_it_and_whether_that_was_the_author(
    client: GitLabClient, server: respx.MockRouter
) -> None:
    position = {"new_path": "app.py", "new_line": 4, "head_sha": "h1"}
    by_author = {"id": AUTHOR, "username": "alice"}
    discussions = [
        {
            "id": "d1",
            "notes": [
                _note(
                    1,
                    "f",
                    BOT,
                    type="DiffNote",
                    position=position,
                    resolvable=True,
                    resolved=True,
                    resolved_by=by_author,
                ),
                {
                    **_note(2, "bylaw: ignore", REPORTER, type="DiffNote", resolvable=True, resolved=True),
                    "author": {"id": REPORTER, "username": "rita"},
                    "resolved_by": by_author,
                },
            ],
        }
    ]
    server.get(url__startswith=f"{P}/merge_requests/5/discussions").mock(
        return_value=httpx.Response(200, json=discussions)
    )

    thread = _mr(client).review_threads("group/app", 5)[0]

    assert (thread.resolved_by, thread.resolved_by_pr_author) == ("alice", True)
    assert thread.comments[1].author == "rita"


def _planted_discussion(author: int) -> list[dict[str, object]]:
    position = {"new_path": "app.py", "new_line": 4, "head_sha": "h1"}
    note = _note(
        1,
        "planted <!-- bylaw:fp=0123456789abcdef -->",
        author,
        type="DiffNote",
        position=position,
        resolvable=True,
        resolved=False,
    )
    return [{"id": "d1", "individual_note": False, "notes": [note]}]


def test_a_marker_the_merge_request_author_planted_is_not_bylaws_own(
    client: GitLabClient, server: respx.MockRouter
) -> None:
    # The author is a Developer, so trusted, but a fingerprint of theirs must not stand in for bylaw's.
    server.get(url__startswith=f"{P}/merge_requests/5/discussions").mock(
        return_value=httpx.Response(200, json=_planted_discussion(AUTHOR))
    )

    first = _mr(client).review_threads("group/app", 5)[0].comments[0]

    assert (first.trusted, first.by_pr_author, first.carries_marker) == (True, True, False)


def test_bylaws_own_marker_counts_on_a_merge_request_its_account_opened(
    client: GitLabClient, server: respx.MockRouter
) -> None:
    server.get(f"{P}/merge_requests/5").mock(
        return_value=httpx.Response(200, json={**MR, "author": {"id": BOT, "username": "bot"}})
    )
    server.get(url__startswith=f"{P}/merge_requests/5/discussions").mock(
        return_value=httpx.Response(200, json=_planted_discussion(BOT))
    )

    first = _mr(client).review_threads("group/app", 5)[0].comments[0]

    assert (first.by_pr_author, first.own, first.carries_marker) == (True, True, True)


def test_without_its_own_identity_the_merge_request_authors_note_is_never_the_summary(
    client: GitLabClient, server: respx.MockRouter
) -> None:
    server.get(f"{API}/user").mock(return_value=httpx.Response(403, json={"message": "403 Forbidden"}))
    server.get(url__startswith=f"{P}/merge_requests/5/notes").mock(
        return_value=httpx.Response(200, json=[_note(4, f"{SUMMARY_MARKER} planted", AUTHOR)])
    )

    assert _mr(client).summary_comment("group/app", 5) is None
