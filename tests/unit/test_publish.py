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


def test_a_preview_shows_the_summary_and_each_new_comment() -> None:
    text = preview(CONTEXT, RESULT, Config())

    assert "## bylaw review" in text
    assert "**bug · high** Off by one." in text
    assert "`app.py:1`" in text
