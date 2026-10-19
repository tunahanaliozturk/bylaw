"""Learning (ADR 0022): outcomes at close, the record format, and what may become a suggestion."""

from bylaw.config import Learn
from bylaw.learn import Record, StoredFinding, parse_records, suggestions
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


def _record(number: int, outcome: str, by: str | None = "maintainer", **finding: str) -> Record:
    fields = {"category": "rule", "rule": "ruff:S101", "file": "tests/unit/a.py", **finding}
    stored = StoredFinding(fingerprint=f"{number:016x}", outcome=outcome, by=by, **fields)
    return Record(
        pull_request=number, author="author", merged=True, closed_at=None, head_sha="h", findings=(stored,)
    )


def test_three_dismissals_in_three_pull_requests_make_a_suggestion_for_the_shared_directory() -> None:
    records = [
        _record(1, "muted"),
        _record(2, "resolved", by="reviewer"),
        _record(3, "muted", file="tests/integration/b.py"),
    ]

    (suggestion,) = suggestions(records, Learn(enabled=True), ())

    assert (suggestion.rule, suggestion.paths, suggestion.pull_requests) == (
        "ruff:S101",
        ("tests/**",),
        (1, 2, 3),
    )


def test_dismissals_by_the_pull_request_s_own_author_do_not_count() -> None:
    records = [_record(n, "muted", by="author") for n in (1, 2, 3)]

    assert suggestions(records, Learn(enabled=True), ()) == []


def test_a_rule_fixed_as_often_as_it_is_dismissed_is_not_suggested() -> None:
    records = [_record(n, "muted") for n in (1, 2, 3)] + [_record(n, "fixed", by=None) for n in (4, 5, 6)]

    assert suggestions(records, Learn(enabled=True), ()) == []


def test_security_findings_and_findings_that_cite_nothing_are_never_suggested() -> None:
    security = [_record(n, "muted", category="security") for n in (1, 2, 3)]
    uncited = [
        Record(
            pull_request=n,
            author="author",
            merged=True,
            closed_at=None,
            head_sha="h",
            findings=(
                StoredFinding(
                    fingerprint="f", category="bug", rule=None, file="a.py", outcome="muted", by="m"
                ),
            ),
        )
        for n in (4, 5, 6)
    ]

    assert suggestions([*security, *uncited], Learn(enabled=True, suggest=("rule", "bug")), ()) == []


def test_only_the_categories_learn_may_suggest_are_suggested() -> None:
    records = [_record(n, "muted", category="bug") for n in (1, 2, 3)]

    assert suggestions(records, Learn(enabled=True), ()) == []
    assert len(suggestions(records, Learn(enabled=True, suggest=("bug",)), ())) == 1
