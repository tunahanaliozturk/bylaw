from collections.abc import Sequence
from dataclasses import dataclass, field

from bylaw.config import Config
from bylaw.github import ReviewComment, SummaryComment
from bylaw.model import AddedLine, Category, ChangedFile, Finding, ReviewContext, ReviewResult, Severity
from bylaw.plan import Thread, ThreadComment
from bylaw.publish import preview, publish

CONTEXT = ReviewContext(
    base_sha="b" * 40,
    head_sha="h" * 40,
    title="t",
    files=(ChangedFile(path="app.py", status="added", added_lines=(AddedLine(number=1, text="x"),)),),
    rules=(),
    requirements=(),
    findings=(),
    notes=(),
)
RESULT = ReviewResult(
    findings=(
        Finding(
            file="app.py",
            line_start=1,
            line_end=1,
            category=Category.BUG,
            severity=Severity.HIGH,
            message="Off by one.",
        ),
    )
)


@dataclass
class FakeClient:
    threads: list[Thread] = field(default_factory=list)
    summary: SummaryComment | None = None
    reviews: list[list[ReviewComment]] = field(default_factory=list)
    summaries: list[tuple[int | None, str]] = field(default_factory=list)
    resolved: list[tuple[str, bool]] = field(default_factory=list)

    def review_threads(self, repo: str, number: int) -> list[Thread]:
        return self.threads

    def summary_comment(self, repo: str, number: int) -> SummaryComment | None:
        return self.summary

    def create_review(
        self, repo: str, number: int, commit_id: str, body: str, comments: Sequence[ReviewComment]
    ) -> None:
        self.reviews.append(list(comments))

    def upsert_summary(self, repo: str, number: int, comment_id: int | None, body: str) -> None:
        self.summaries.append((comment_id, body))

    def set_thread_resolved(self, thread_id: str, *, resolved: bool) -> None:
        self.resolved.append((thread_id, resolved))


def test_publishing_twice_posts_once_and_resolves_after_the_fix() -> None:
    client = FakeClient()
    publish(client, "octo/app", 5, context=CONTEXT, result=RESULT, config=Config())
    assert [len(review) for review in client.reviews] == [1]

    posted = client.reviews[0][0]
    client.threads = [Thread(id="T1", resolved=False, comments=(ThreadComment(posted.body, trusted=True),))]
    client.summary = SummaryComment(id=7, body=client.summaries[-1][1])
    publish(client, "octo/app", 5, context=CONTEXT, result=RESULT, config=Config())
    assert [len(review) for review in client.reviews] == [1]

    publish(client, "octo/app", 5, context=CONTEXT, result=ReviewResult(), config=Config())
    assert client.resolved == [("T1", True)]
    assert client.summaries[-1][0] == 7


def test_a_thread_read_without_its_older_replies_is_noted_in_the_summary() -> None:
    partial = Thread(id="T1", resolved=False, comments=(), older_replies_unread=True)
    client = FakeClient(threads=[partial])

    publish(client, "octo/app", 5, context=CONTEXT, result=RESULT, config=Config())

    assert "1 long review thread(s) read without older replies" in client.summaries[-1][1]


def test_a_preview_shows_the_summary_and_each_new_comment() -> None:
    text = preview(CONTEXT, RESULT, Config())

    assert "## bylaw review" in text
    assert "**bug · high** Off by one." in text
    assert "`app.py:1`" in text


def test_a_failed_thread_update_still_records_what_was_done() -> None:
    import pytest  # noqa: PLC0415

    from bylaw.github import GitHubError  # noqa: PLC0415
    from bylaw.render import read_state  # noqa: PLC0415

    def ours(thread_id: str, line: int) -> Thread:
        fp = {"T1": "a" * 16, "T2": "b" * 16}[thread_id]
        marker = ThreadComment(f"text\n<!-- bylaw:fp={fp} -->", trusted=True)
        return Thread(id=thread_id, resolved=False, comments=(marker,), line=line)

    class Flaky(FakeClient):
        def set_thread_resolved(self, thread_id: str, *, resolved: bool) -> None:
            if thread_id == "T2":
                raise GitHubError("GitHub API rate limit reached")
            super().set_thread_resolved(thread_id, resolved=resolved)

    client = Flaky(threads=[ours("T1", 1), ours("T2", 2)])

    with pytest.raises(GitHubError):
        publish(client, "octo/app", 5, context=CONTEXT, result=ReviewResult(), config=Config())

    assert client.resolved == [("T1", True)]
    assert read_state(client.summaries[-1][1]).auto_resolved == frozenset({"T1"})


def test_the_review_memory_is_written_into_the_summary_state() -> None:
    from bylaw.model import ReviewMemory  # noqa: PLC0415
    from bylaw.render import read_state  # noqa: PLC0415

    client = FakeClient()
    memory = ReviewMemory(head_sha="h" * 40, inputs="0" * 16, tokens=10, run_tokens=10)

    publish(client, "octo/app", 5, context=CONTEXT, result=RESULT, config=Config(), memory=memory)

    assert read_state(client.summaries[-1][1]).review == memory


def test_a_human_written_summary_never_supplies_the_review_memory() -> None:
    from bylaw.incremental import trusted_memory  # noqa: PLC0415
    from bylaw.model import ReviewMemory  # noqa: PLC0415
    from bylaw.plan import Plan, State  # noqa: PLC0415
    from bylaw.render import summary_body  # noqa: PLC0415

    memory = ReviewMemory(head_sha="h" * 40, inputs="0" * 16)
    plan = Plan((), (), (), (), (), (), (), State(auto_resolved=frozenset(), review=memory))
    body = summary_body(CONTEXT, RESULT, plan)

    assert trusted_memory(SummaryComment(id=1, body=body, bot=True)) == memory
    assert trusted_memory(SummaryComment(id=1, body=body, bot=False)) is None
    assert trusted_memory(None) is None
