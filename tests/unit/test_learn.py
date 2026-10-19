"""Learning (ADR 0022): outcomes at close, the record format, and what may become a suggestion."""

from bylaw.learn import Record, parse_records
from bylaw.plan import Outcome, Thread, ThreadComment, close_outcomes

FP = "0123456789abcdef"
OPEN = {FP: Outcome(status="open", category="rule", rule="ruff:S101", file="tests/a.py")}


def _thread(*replies: ThreadComment, resolved_by: str | None = None, trusted: bool = True) -> Thread:
    first = ThreadComment(f"finding\n\n<!-- bylaw:fp={FP} -->", trusted=trusted)
    return Thread(
        id="T1",
        resolved=resolved_by is not None,
        comments=(first, *replies),
        resolved_by=resolved_by,
        resolved_by_pr_author=resolved_by == "author",
    )


def test_a_mute_made_after_the_last_run_counts_when_the_pull_request_closes() -> None:
    mute = ThreadComment("bylaw: ignore", trusted=True, author="maintainer")

    closed = close_outcomes(OPEN, [_thread(mute)], frozenset())

    assert (closed[FP].status, closed[FP].by) == ("muted", "maintainer")


def test_at_close_a_thread_resolved_by_its_author_or_by_bylaw_accepts_nothing() -> None:
    assert close_outcomes(OPEN, [_thread(resolved_by="author")], frozenset())[FP].status == "open"
    assert close_outcomes(OPEN, [_thread(resolved_by="bot")], frozenset({"T1"}))[FP].status == "open"
    assert close_outcomes(OPEN, [_thread(resolved_by="reviewer")], frozenset())[FP].by == "reviewer"


def test_at_close_a_thread_whose_marker_an_untrusted_account_wrote_changes_nothing() -> None:
    mute = ThreadComment("bylaw: ignore", trusted=True, author="maintainer")

    assert close_outcomes(OPEN, [_thread(mute, trusted=False)], frozenset()) == OPEN


def test_store_files_that_do_not_read_as_a_record_are_left_out() -> None:
    good = Record(pull_request=3, author="a", merged=True, closed_at=None, head_sha="h", findings=())
    texts = {
        "pulls/3.json": good.model_dump_json(),
        "pulls/4.json": "not json",
        "pulls/5.json": '{"schema_version": 2, "pull_request": 5}',
        "pulls/6.json": None,
    }

    assert parse_records(texts) == [good]
