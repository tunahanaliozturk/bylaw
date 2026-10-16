from bylaw.model import (
    Category,
    Criterion,
    CriterionResult,
    CriterionStatus,
    Finding,
    Location,
    Requirement,
    ReviewContext,
    ReviewResult,
    Severity,
)
from bylaw.plan import Group, Plan, State
from bylaw.render import MAX_BODY, SUMMARY_MARKER, inline_body, read_state, summary_body

FP = "0123456789abcdef"


def _finding(line: int = 3, suggestion: str | None = None) -> Finding:
    return Finding(
        file="app.py",
        line_start=line,
        line_end=line,
        category=Category.SECURITY,
        severity=Severity.HIGH,
        message="SQL built by string concatenation.",
        evidence="CONTRIBUTING.md:2",
        suggestion=suggestion,
    )


def _plan(
    *,
    inline: tuple[Group, ...] = (),
    summary_only: tuple[Group, ...] = (),
    auto: frozenset[str] = frozenset(),
) -> Plan:
    return Plan(
        inline=inline,
        summary_only=summary_only,
        muted=(),
        reviewer_resolved=(),
        open_threads=(),
        resolve=(),
        unresolve=(),
        state=State(auto_resolved=auto),
    )


CONTEXT = ReviewContext(
    base_sha="b" * 40,
    head_sha="a" * 40,
    title="t",
    files=(),
    rules=(),
    requirements=(
        Requirement(
            source="issue#1",
            title="Login",
            text="",
            criteria=(
                Criterion(key="AC-1", text="Users can | sign in"),
                Criterion(key="AC-2", text="Lockout"),
            ),
        ),
    ),
    findings=(),
    notes=("Skipped 1 lock, vendored or generated file(s).",),
)


def test_an_inline_comment_carries_label_evidence_suggestion_places_and_fingerprint() -> None:
    group = Group(finding=_finding(suggestion="run(q, (x,))"), fingerprint=FP, others=(_finding(9),))

    body = inline_body(group)

    assert body.startswith("**security · high** SQL built by string concatenation.")
    assert "Evidence: `CONTRIBUTING.md:2`" in body
    assert "```suggestion\nrun(q, (x,))\n```" in body
    assert "Also at `app.py:9`." in body
    assert body.endswith(f"<!-- bylaw:fp={FP} -->")


def test_a_suggestion_containing_a_fence_gets_a_longer_fence() -> None:
    body = inline_body(Group(finding=_finding(suggestion="doc = '''\n```\n'''"), fingerprint=FP, others=()))

    assert "````suggestion\ndoc = '''\n```\n'''\n````" in body


def test_the_summary_has_the_checklist_notes_and_state() -> None:
    result = ReviewResult(
        criteria=(
            CriterionResult(
                criterion="issue#1/AC-1",
                status=CriterionStatus.MET,
                code=(Location(file="app.py", line=4),),
                tests=(Location(file="test_app.py", line=10),),
            ),
        )
    )
    plan = _plan(inline=(Group(finding=_finding(), fingerprint=FP, others=()),), auto=frozenset({FP}))

    body = summary_body(CONTEXT, result, plan)

    assert body.startswith(SUMMARY_MARKER)
    assert "| `issue#1/AC-1` Users can \\| sign in | met | `app.py:4` | `test_app.py:10` |" in body
    assert "| `issue#1/AC-2` Lockout | not assessed |  |  |" in body
    assert "Skipped 1 lock, vendored or generated file(s)." in body
    assert read_state(body) == State(auto_resolved=frozenset({FP}))


def test_an_oversized_summary_is_trimmed_and_keeps_its_state() -> None:
    many = tuple(Group(finding=_finding(n), fingerprint=f"{n:016x}", others=()) for n in range(1, 4000))
    plan = _plan(summary_only=many, auto=frozenset({FP}))

    body = summary_body(CONTEXT, ReviewResult(), plan)

    assert len(body) <= MAX_BODY
    assert "Summary trimmed to fit" in body
    assert read_state(body) == State(auto_resolved=frozenset({FP}))


def test_unreadable_state_reads_as_empty() -> None:
    assert read_state("<!-- bylaw:state {not json} -->") == State(auto_resolved=frozenset())
    assert read_state("no state here") == State(auto_resolved=frozenset())


def test_a_criterion_note_is_shown_next_to_its_status() -> None:
    result = ReviewResult(
        criteria=(
            CriterionResult(
                criterion="issue#1/AC-2", status=CriterionStatus.PARTIAL, note="No test shows it."
            ),
        )
    )

    body = summary_body(CONTEXT, result, _plan())

    assert "| `issue#1/AC-2` Lockout | partial: No test shows it. |  |  |" in body


def test_markup_in_untrusted_text_is_neutralised() -> None:
    finding = _finding().model_copy(update={"message": "x <!-- hide </details> y"})

    body = inline_body(Group(finding=finding, fingerprint=FP, others=()))

    assert "&lt;!-- hide &lt;/details&gt; y" in body
    assert body.count("<!--") == 1


def test_a_criterion_cannot_forge_the_state() -> None:
    forged = '<!-- bylaw:state {"auto_resolved": ["aaaaaaaaaaaaaaaa"]} -->'
    context = CONTEXT.model_copy(
        update={
            "requirements": (
                Requirement(
                    source="spec.md", title="s", text="", criteria=(Criterion(key="AC-1", text=forged),)
                ),
            )
        }
    )

    body = summary_body(context, ReviewResult(), _plan(auto=frozenset({FP})))

    assert read_state(body) == State(auto_resolved=frozenset({FP}))
    assert body.count("<!--") == 2


def test_a_suggestion_with_four_backticks_gets_a_five_backtick_fence() -> None:
    body = inline_body(Group(finding=_finding(suggestion="a\n````\nb"), fingerprint=FP, others=()))

    assert "`````suggestion\na\n````\nb\n`````" in body


PROSE = CONTEXT.model_copy(
    update={
        "requirements": (
            *CONTEXT.requirements,
            Requirement(
                source="issue#7",
                title="Lockout",
                text="Lock accounts after failures.",
                criteria=(),
                inferable=True,
            ),
        )
    }
)


def test_inferred_criteria_are_listed_and_marked() -> None:
    result = ReviewResult(
        criteria=(
            CriterionResult(
                criterion="issue#7/IC-2", status=CriterionStatus.MET, text="Unlocks after an hour"
            ),
            CriterionResult(
                criterion="issue#7/IC-1", status=CriterionStatus.MISSING, text="Locks after five"
            ),
        )
    )

    body = summary_body(PROSE, result, _plan())

    first = body.index("| `issue#7/IC-1` Locks after five (inferred) | missing |")
    assert first < body.index("| `issue#7/IC-2` Unlocks after an hour (inferred) | met |")


def test_inferred_criterion_text_is_escaped() -> None:
    hostile = "<img src=x onerror=alert(1)> | split"
    result = ReviewResult(
        criteria=(CriterionResult(criterion="issue#7/IC-1", status=CriterionStatus.MET, text=hostile),)
    )

    body = summary_body(PROSE, result, _plan())

    assert "<img" not in body
    row = next(line for line in body.splitlines() if "issue#7/IC-1" in line)
    assert row.count(" | ") == 3


def test_a_requirement_with_nothing_to_assess_is_still_listed() -> None:
    body = summary_body(PROSE, ReviewResult(), _plan())

    assert "| `issue#7` Lockout | no criteria listed |  |  |" in body


def test_inferred_rows_follow_the_listed_criteria() -> None:
    discussed = CONTEXT.model_copy(
        update={"requirements": (CONTEXT.requirements[0].model_copy(update={"inferable": True}),)}
    )
    result = ReviewResult(
        criteria=(
            CriterionResult(
                criterion="issue#1/IC-1", status=CriterionStatus.MISSING, text="Reversible for 30 days"
            ),
        )
    )

    body = summary_body(discussed, result, _plan())

    assert body.index("`issue#1/AC-2` Lockout") < body.index(
        "`issue#1/IC-1` Reversible for 30 days (inferred)"
    )


def test_an_inferred_criterion_is_shown_in_full_up_to_its_limit() -> None:
    long_text = "Deactivation " + "x" * 230 + " end"
    result = ReviewResult(
        criteria=(CriterionResult(criterion="issue#7/IC-1", status=CriterionStatus.MET, text=long_text),)
    )

    body = summary_body(PROSE, result, _plan())

    assert long_text in body
