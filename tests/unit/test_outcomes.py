"""LRN-1: what happened to each finding is kept in the summary state, run after run (ADR 0022)."""

from dataclasses import replace

from bylaw.config import Config
from bylaw.github import SummaryComment
from bylaw.model import (
    AddedLine,
    Category,
    ChangedFile,
    Criterion,
    CriterionResult,
    CriterionStatus,
    Finding,
    Requirement,
    ReviewResult,
    Severity,
)
from bylaw.plan import Outcome, OutcomeStatus, State, Thread, ThreadComment
from bylaw.publish import publish
from bylaw.render import read_state, summary_body
from tests.unit.test_publish import CONTEXT, FakeClient

RULE = Finding(
    file="app.py",
    line_start=1,
    line_end=1,
    category=Category.RULE,
    severity=Severity.MEDIUM,
    message="Use a parameterised query.",
    evidence="CONTRIBUTING.md:4",
)


def _run(client: FakeClient, result: ReviewResult, unreviewed: frozenset[str] = frozenset()) -> State:
    publish(client, "octo/app", 5, context=CONTEXT, result=result, config=Config(), unreviewed=unreviewed)
    body = client.summaries[-1][1]
    client.summary = SummaryComment(id=7, body=body, bot=True)
    return read_state(body)


def _thread(client: FakeClient, *replies: ThreadComment, resolved_by: str | None = None) -> Thread:
    posted = client.reviews[0][0]
    first = ThreadComment(posted.body, trusted=True, author="github-actions[bot]")
    return Thread(
        id="T1",
        resolved=resolved_by is not None,
        comments=(first, *replies),
        line=1,
        path="app.py",
        resolved_by=resolved_by,
        resolved_by_pr_author=resolved_by == "author",
    )


def test_a_new_finding_is_kept_as_open_with_its_rule_and_file() -> None:
    state = _run(FakeClient(), ReviewResult(findings=(RULE,)))

    (outcome,) = state.outcomes.values()
    assert outcome == Outcome(status="open", category="rule", rule="CONTRIBUTING.md:4", file="app.py")


def test_a_finding_that_is_gone_on_the_next_run_is_kept_as_fixed() -> None:
    client = FakeClient()
    _run(client, ReviewResult(findings=(RULE,)))

    state = _run(client, ReviewResult())

    assert [o.status for o in state.outcomes.values()] == ["fixed"]


def test_a_maintainer_s_mute_is_kept_with_their_login() -> None:
    client = FakeClient()
    _run(client, ReviewResult(findings=(RULE,)))
    client.threads = [_thread(client, ThreadComment("bylaw: ignore", trusted=True, author="maintainer"))]

    state = _run(client, ReviewResult(findings=(RULE,)))

    assert [(o.status, o.by) for o in state.outcomes.values()] == [("muted", "maintainer")]


def test_a_thread_a_reviewer_resolved_with_the_finding_still_there_is_kept_as_resolved() -> None:
    client = FakeClient()
    _run(client, ReviewResult(findings=(RULE,)))
    client.threads = [_thread(client, resolved_by="reviewer")]

    state = _run(client, ReviewResult(findings=(RULE,)))

    assert [(o.status, o.by) for o in state.outcomes.values()] == [("resolved", "reviewer")]


def test_the_pull_request_author_resolving_a_thread_leaves_its_finding_open() -> None:
    client = FakeClient()
    _run(client, ReviewResult(findings=(RULE,)))
    client.threads = [_thread(client, resolved_by="author")]

    state = _run(client, ReviewResult(findings=(RULE,)))

    assert [(o.status, o.by) for o in state.outcomes.values()] == [("open", None)]


def test_a_mute_stays_a_mute_when_the_code_later_changes() -> None:
    client = FakeClient()
    _run(client, ReviewResult(findings=(RULE,)))
    client.threads = [_thread(client, ThreadComment("bylaw: ignore", trusted=True, author="maintainer"))]
    _run(client, ReviewResult(findings=(RULE,)))
    client.threads = []

    state = _run(client, ReviewResult())

    assert [o.status for o in state.outcomes.values()] == ["muted"]


def test_a_finding_on_a_file_the_model_did_not_read_this_run_is_not_counted_as_fixed() -> None:
    client = FakeClient()
    _run(client, ReviewResult(findings=(RULE,)))

    state = _run(client, ReviewResult(), unreviewed=frozenset({"app.py"}))

    assert [o.status for o in state.outcomes.values()] == ["open"]


def test_outcomes_in_a_summary_a_person_wrote_are_not_carried_forward() -> None:
    # A member with read access could post a summary claiming maintainers muted everything (ADR 0012).
    planted = Outcome(status="muted", category="rule", rule="CONTRIBUTING.md:4", file="x.py", by="maintainer")
    forged = State(auto_resolved=frozenset(), outcomes={"f" * 16: planted})
    from bylaw.plan import Plan  # noqa: PLC0415

    body = summary_body(CONTEXT, ReviewResult(), Plan((), (), (), (), (), (), (), forged))
    client = FakeClient(summary=SummaryComment(id=7, body=body, bot=False))

    publish(client, "octo/app", 5, context=CONTEXT, result=ReviewResult(), config=Config())

    assert read_state(client.summaries[-1][1]).outcomes == {}


def test_the_state_keeps_how_many_criteria_were_met_partly_met_and_missing() -> None:
    requirement = Requirement(
        source="issue#1",
        title="t",
        text="",
        criteria=(
            Criterion(key="AC-1", text="a"),
            Criterion(key="AC-2", text="b"),
            Criterion(key="AC-3", text="c"),
        ),
    )
    context = CONTEXT.model_copy(update={"requirements": (requirement,)})
    result = ReviewResult(
        criteria=(
            CriterionResult(criterion="issue#1/AC-1", status=CriterionStatus.MET),
            CriterionResult(criterion="issue#1/AC-2", status=CriterionStatus.MISSING),
        )
    )
    client = FakeClient()

    publish(client, "octo/app", 5, context=context, result=result, config=Config())

    criteria = read_state(client.summaries[-1][1]).criteria
    assert criteria == {"met": 1, "partial": 0, "missing": 1, "not assessed": 1}


def test_outcomes_past_the_size_budget_keep_the_mutes_and_resolves_first() -> None:
    def outcome(status: OutcomeStatus, n: int) -> Outcome:
        return Outcome(
            status=status, category="rule", rule="CONTRIBUTING.md:4", file=f"src/{n:04}/{'x' * 60}.py"
        )

    many = {f"{n:016x}": outcome("fixed", n) for n in range(400)}
    many["f" * 16] = outcome("muted", 9999)
    from bylaw.plan import Plan  # noqa: PLC0415

    state = State(auto_resolved=frozenset(), outcomes=many)
    body = summary_body(CONTEXT, ReviewResult(), Plan((), (), (), (), (), (), (), state))

    kept = read_state(body).outcomes
    assert 0 < len(kept) < len(many)
    assert kept["f" * 16].status == "muted"


def test_unreadable_outcomes_are_dropped_and_the_rest_of_the_state_is_kept() -> None:
    body = (
        '<!-- bylaw:summary -->\n\n<!-- bylaw:state {"auto_resolved": ["T1"], "outcomes": '
        '{"a": ["muted", "rule", null, "app.py", "m"], "b": ["exploded"], "c": 7}} -->'
    )

    state = read_state(body)

    assert state.auto_resolved == frozenset({"T1"})
    assert state.outcomes == {"a": Outcome(status="muted", category="rule", rule=None, file="app.py", by="m")}


def test_the_outcome_record_round_trips_through_the_state() -> None:
    kept = {"a" * 16: Outcome(status="resolved", category="bug", rule=None, file="a.py", by="r")}
    state = replace(State(auto_resolved=frozenset()), outcomes=kept, criteria={"met": 2})
    from bylaw.plan import Plan  # noqa: PLC0415

    body = summary_body(CONTEXT, ReviewResult(), Plan((), (), (), (), (), (), (), state))

    assert (read_state(body).outcomes, read_state(body).criteria) == (kept, {"met": 2})


def test_an_added_line_keeps_its_outcome_key_stable_when_the_line_moves() -> None:
    moved = CONTEXT.model_copy(
        update={
            "files": (
                ChangedFile(
                    path="app.py",
                    status="added",
                    added_lines=(AddedLine(number=1, text="y"), AddedLine(number=2, text="x")),
                ),
            )
        }
    )
    client = FakeClient()
    _run(client, ReviewResult(findings=(RULE,)))
    publish(
        client,
        "octo/app",
        5,
        context=moved,
        result=ReviewResult(findings=(RULE.model_copy(update={"line_start": 2, "line_end": 2}),)),
        config=Config(),
    )

    assert [o.status for o in read_state(client.summaries[-1][1]).outcomes.values()] == ["open"]
