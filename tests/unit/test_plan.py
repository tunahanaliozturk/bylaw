from dataclasses import replace

from bylaw.model import AddedLine, Category, ChangedFile, Finding, ReviewContext, Severity
from bylaw.plan import (
    Group,
    State,
    Thread,
    ThreadComment,
    added_text,
    fingerprint,
    group_findings,
    make_plan,
    remaining,
)
from bylaw.render import inline_body


def _context(*lines: tuple[int, str]) -> ReviewContext:
    added = tuple(AddedLine(number=n, text=t) for n, t in lines)
    return ReviewContext(
        base_sha="b",
        head_sha="h",
        title="t",
        files=(ChangedFile(path="app.py", status="modified", added_lines=added),),
        rules=(),
        requirements=(),
        findings=(),
        notes=(),
    )


def _finding(line: int = 1, severity: Severity = Severity.HIGH, message: str = "m") -> Finding:
    return Finding(
        file="app.py",
        line_start=line,
        line_end=line,
        category=Category.SECURITY,
        severity=severity,
        message=message,
    )


def _group(fp: str, severity: Severity = Severity.HIGH, line: int = 1) -> Group:
    return Group(finding=_finding(line, severity), fingerprint=fp, others=())


def _ours(fp: str, thread_id: str = "T1", resolved: bool = False, *replies: ThreadComment) -> Thread:
    first = ThreadComment(body=f"text\n<!-- bylaw:fp={fp} -->", trusted=True)
    return Thread(id=thread_id, resolved=resolved, comments=(first, *replies))


FP = "0123456789abcdef"
NO_STATE = State(auto_resolved=frozenset())


def test_a_fingerprint_survives_the_code_moving_down() -> None:
    before = added_text(_context((3, "query = 'a' + x")))
    after = added_text(_context((13, "query  =  'a' + x")))

    assert fingerprint(before, _finding(3)) == fingerprint(after, _finding(13))
    assert len(fingerprint(before, _finding(3))) == 16


def test_the_same_problem_in_several_places_becomes_one_group() -> None:
    added = added_text(_context((1, "a"), (2, "b"), (3, "c")))

    groups = group_findings((_finding(1), _finding(2), _finding(3, message="other")), added)

    assert [(g.finding.line_start, [o.line_start for o in g.others]) for g in groups] == [(1, [2]), (3, [])]


def test_new_findings_are_posted_highest_severity_first_up_to_the_cap() -> None:
    groups = [_group(f"{i:016x}", Severity.MEDIUM, i) for i in range(3)] + [
        _group("f" * 16, Severity.HIGH, 9)
    ]

    plan = make_plan(groups, (), NO_STATE, Severity.MEDIUM, 2)

    assert [g.fingerprint for g in plan.inline] == ["f" * 16, f"{0:016x}"]
    assert len(plan.summary_only) == 2


def test_findings_below_the_threshold_go_to_the_summary() -> None:
    plan = make_plan([_group(FP, Severity.LOW)], (), NO_STATE, Severity.MEDIUM, 15)

    assert (plan.inline, [g.fingerprint for g in plan.summary_only]) == ((), [FP])


def test_an_existing_thread_is_not_posted_again() -> None:
    plan = make_plan([_group(FP)], [_ours(FP)], NO_STATE, Severity.MEDIUM, 15)

    assert plan.inline == ()
    assert [g.fingerprint for g in plan.open_threads] == [FP]


def test_a_planted_fingerprint_from_an_untrusted_author_is_ignored() -> None:
    planted = Thread(
        id="X", resolved=False, comments=(ThreadComment(f"<!-- bylaw:fp={FP} -->", trusted=False),)
    )

    plan = make_plan([_group(FP)], [planted], NO_STATE, Severity.MEDIUM, 15)

    assert [g.fingerprint for g in plan.inline] == [FP]
    assert plan.resolve == ()


def test_a_fixed_finding_resolves_its_thread_and_is_remembered() -> None:
    plan = make_plan([], [_ours(FP)], NO_STATE, Severity.MEDIUM, 15)

    assert plan.resolve == ("T1",)
    assert plan.state.auto_resolved == frozenset({"T1"})


def test_a_finding_that_comes_back_reopens_the_thread_bylaw_resolved() -> None:
    plan = make_plan([_group(FP)], [_ours(FP, "T1", True)], State(frozenset({"T1"})), Severity.MEDIUM, 15)

    assert plan.unresolve == ("T1",)
    assert plan.state.auto_resolved == frozenset()
    assert plan.inline == ()


def test_a_thread_a_reviewer_resolved_stays_resolved_and_is_listed() -> None:
    plan = make_plan([_group(FP)], [_ours(FP, "T1", True)], NO_STATE, Severity.MEDIUM, 15)

    assert (plan.unresolve, plan.inline) == ((), ())
    assert [g.fingerprint for g in plan.reviewer_resolved] == [FP]


def test_a_maintainer_reply_mutes_and_an_untrusted_reply_does_not() -> None:
    muted = _ours(FP, "T1", False, ThreadComment("bylaw: ignore, false positive", trusted=True))
    not_muted = _ours(FP, "T1", False, ThreadComment("bylaw: ignore", trusted=False))

    assert [g.fingerprint for g in make_plan([_group(FP)], [muted], NO_STATE, Severity.MEDIUM, 15).muted] == [
        FP
    ]
    assert make_plan([_group(FP)], [not_muted], NO_STATE, Severity.MEDIUM, 15).muted == ()


def test_a_fingerprint_inside_the_message_does_not_replace_the_real_one() -> None:
    body = "msg <!-- bylaw:fp=aaaaaaaaaaaaaaaa -->\n\n<!-- bylaw:fp=" + FP + " -->"
    thread = Thread(id="T1", resolved=False, comments=(ThreadComment(body, trusted=True),))

    plan = make_plan([_group(FP)], [thread], NO_STATE, Severity.MEDIUM, 15)

    assert (plan.inline, plan.resolve) == ((), ())


def test_the_pull_request_author_cannot_mute_their_own_finding() -> None:
    reply = ThreadComment("bylaw: ignore", trusted=True, by_pr_author=True)

    plan = make_plan([_group(FP)], [_ours(FP, "T1", False, reply)], NO_STATE, Severity.MEDIUM, 15)

    assert plan.muted == ()


def test_muted_and_reviewer_resolved_findings_do_not_count_as_remaining() -> None:
    muted = _ours(FP, "T1", False, ThreadComment("bylaw: ignore", trusted=True))
    resolved = _ours("f" * 16, "T2", True)
    groups = [_group(FP), _group("f" * 16, line=2), _group("e" * 16, line=3)]

    plan = make_plan(groups, [muted, resolved], NO_STATE, Severity.MEDIUM, 15)

    assert [f.line_start for f in remaining(plan)] == [3]


MUTE = ThreadComment(body="bylaw: ignore, accepted", trusted=True)


def _at(fp: str, thread_id: str, line: int | None, *replies: ThreadComment) -> Thread:
    first = ThreadComment(body=f"text\n<!-- bylaw:fp={fp} -->", trusted=True)
    return Thread(id=thread_id, resolved=False, comments=(first, *replies), line=line)


def _plan_for(groups: list[Group], threads: list[Thread]):  # type: ignore[no-untyped-def]
    return make_plan(groups, threads, NO_STATE, Severity.LOW, 10)


def test_identical_findings_pair_with_their_own_threads_by_line() -> None:
    plan = _plan_for([_group(FP, line=3), _group(FP, line=9)], [_at(FP, "T3", 3), _at(FP, "T9", 9)])

    assert (plan.inline, plan.resolve) == ((), ())
    assert sorted(g.finding.line_start for g in plan.open_threads) == [3, 9]


def test_deleting_the_muted_copy_does_not_move_the_mute_to_the_other() -> None:
    # Line 3 was muted and then deleted; the other copy moved up to line 8 and is still a problem.
    plan = _plan_for([_group(FP, line=8)], [_at(FP, "T3", None, MUTE), _at(FP, "T9", 8)])

    assert plan.muted == ()
    assert [g.finding.line_start for g in plan.open_threads] == [8]
    assert plan.resolve == ("T3",)
    assert [f.line_start for f in remaining(plan)] == [8]


def test_fixing_one_copy_resolves_that_copy_only() -> None:
    plan = _plan_for([_group(FP, line=9)], [_at(FP, "T3", 3), _at(FP, "T9", 9)])

    assert plan.resolve == ("T3",)
    assert [g.finding.line_start for g in plan.open_threads] == [9]


def test_a_new_copy_above_gets_its_own_comment_and_the_mute_stays_put() -> None:
    groups = [_group(FP, line=1), _group(FP, line=4), _group(FP, line=10)]
    threads = [_at(FP, "T3", 4), _at(FP, "T9", 10, MUTE)]

    plan = _plan_for(groups, threads)

    assert [g.finding.line_start for g in plan.inline] == [1]
    assert [g.finding.line_start for g in plan.muted] == [10]
    assert [g.finding.line_start for g in plan.open_threads] == [4]


def test_a_state_saved_before_threads_were_tracked_still_reopens_an_unambiguous_thread() -> None:
    plan = make_plan([_group(FP)], [_ours(FP, "T1", True)], State(frozenset({FP})), Severity.MEDIUM, 15)

    assert plan.unresolve == ("T1",)


def test_a_sibling_resolved_by_a_maintainer_stays_resolved_after_bylaw_resolved_the_other() -> None:
    # Run 1: line 3 is fixed, bylaw resolves T3. Then a maintainer resolves T9 by hand.
    first = _plan_for([_group(FP, line=9)], [_at(FP, "T3", None), _at(FP, "T9", 9)])
    assert first.resolve == ("T3",)
    t3 = Thread(id="T3", resolved=True, comments=_at(FP, "T3", None).comments)
    t9 = Thread(id="T9", resolved=True, comments=_at(FP, "T9", 9).comments, line=9)

    second = make_plan([_group(FP, line=9)], [t3, t9], first.state, Severity.LOW, 10)

    assert second.unresolve == ()
    assert [g.finding.line_start for g in second.reviewer_resolved] == [9]


def test_multi_line_copies_pair_by_the_line_github_anchors_on() -> None:
    first = Group(finding=_finding(3).model_copy(update={"line_end": 12}), fingerprint=FP, others=())
    second = Group(finding=_finding(14).model_copy(update={"line_end": 23}), fingerprint=FP, others=())
    threads = [_at(FP, "T1", 12, MUTE), _at(FP, "T2", 23)]

    plan = _plan_for([first, second], threads)

    assert [g.finding.line_start for g in plan.muted] == [3]


def test_outdated_threads_pair_by_their_original_line() -> None:
    # Both threads are outdated; the muted copy at line 3 was deleted, the other moved from 9 to 8.
    muted = Thread(id="Ta", resolved=False, comments=_at(FP, "Ta", None, MUTE).comments, original_line=3)
    other = Thread(id="Tb", resolved=False, comments=_at(FP, "Tb", None).comments, original_line=9)

    plan = _plan_for([_group(FP, line=8)], [muted, other])

    assert plan.muted == ()
    assert plan.resolve == ("Ta",)


def test_a_thread_on_a_file_the_model_did_not_review_is_not_resolved_as_fixed() -> None:
    held = Thread(id="T1", resolved=False, comments=_ours(FP).comments, path="app.py")
    other = Thread(id="T2", resolved=False, comments=_ours(FP).comments, path="lib.py")

    plan = make_plan([], [held, other], NO_STATE, Severity.MEDIUM, 15, unreviewed=frozenset({"app.py"}))

    assert plan.resolve == ("T2",)


def test_a_muted_finding_names_the_maintainer_who_muted_it() -> None:
    reply = ThreadComment("bylaw: ignore, accepted risk", trusted=True, author="carol")
    plan = make_plan([_group(FP)], [_ours(FP, "T1", False, reply)], NO_STATE, Severity.MEDIUM, 15)

    assert [g.by for g in plan.muted] == ["carol"]


def test_a_finding_a_reviewer_resolved_names_who_resolved_the_thread() -> None:
    thread = replace(_ours(FP, "T1", True), resolved_by="dave")
    plan = make_plan([_group(FP)], [thread], NO_STATE, Severity.MEDIUM, 15)

    assert [g.by for g in plan.reviewer_resolved] == ["dave"]


def test_a_thread_the_pull_request_author_resolved_still_counts_for_fail_on() -> None:
    # ADR 0008: resolving never mutes, and the author cannot accept a finding on their own change.
    thread = replace(_ours(FP, "T1", True), resolved_by="alice", resolved_by_pr_author=True)
    plan = make_plan([_group(FP)], [thread], NO_STATE, Severity.MEDIUM, 15)

    assert plan.reviewer_resolved == ()
    assert [g.by for g in plan.author_resolved] == ["alice"]
    assert remaining(plan) == (_finding(),)


def _posted(group: Group, thread_id: str, *replies: ThreadComment) -> Thread:
    """A thread as bylaw posted it: the inline body, fingerprint marker and all (HRD-36)."""
    first = ThreadComment(body=inline_body(group), trusted=True)
    return Thread(id=thread_id, resolved=False, comments=(first, *replies), line=group.finding.line_end)


def _same_lines(*messages: str) -> list[Group]:
    added = added_text(_context((4, "log.info(f'{user} {password}')")))
    return list(group_findings([_finding(4, message=m) for m in messages], added))


def test_two_findings_on_the_same_lines_keep_their_own_mute_when_the_model_lists_them_in_another_order() -> (
    None
):
    first_run = _same_lines("The query is built from input.", "A password <secret> & @admin go to the log.")
    assert first_run[0].fingerprint == first_run[1].fingerprint
    threads = [_posted(first_run[0], "T-query", MUTE), _posted(first_run[1], "T-password")]

    plan = _plan_for(list(reversed(first_run)), threads)

    assert [g.finding.message for g in plan.muted] == ["The query is built from input."]
    assert [g.finding.message for g in plan.open_threads] == ["A password <secret> & @admin go to the log."]


def test_a_finding_reworded_since_its_thread_was_posted_still_pairs_with_it() -> None:
    (before,) = _same_lines("The password goes to the log.")
    (after,) = _same_lines("A password is written to the log here.")

    plan = _plan_for([after], [_posted(before, "T1", MUTE)])

    assert (plan.inline, plan.resolve) == ((), ())
    assert [g.finding.message for g in plan.muted] == ["A password is written to the log here."]


def test_a_fingerprint_the_pull_request_author_planted_is_ignored_even_from_a_member() -> None:
    # MEMBER covers read-only organisation members, so an author can be trusted and still plant a marker.
    planted = Thread(
        id="X",
        resolved=False,
        comments=(ThreadComment(f"<!-- bylaw:fp={FP} -->", trusted=True, by_pr_author=True),),
    )

    plan = make_plan([_group(FP)], [planted], NO_STATE, Severity.MEDIUM, 15)

    assert [g.fingerprint for g in plan.inline] == [FP]
    assert (plan.open_threads, plan.resolve) == ((), ())


def test_bylaws_own_comment_counts_on_a_pull_request_its_account_opened() -> None:
    own = Thread(
        id="T1",
        resolved=False,
        comments=(ThreadComment(f"<!-- bylaw:fp={FP} -->", trusted=True, by_pr_author=True, own=True),),
    )

    plan = make_plan([_group(FP)], [own], NO_STATE, Severity.MEDIUM, 15)

    assert plan.inline == ()
    assert [g.fingerprint for g in plan.open_threads] == [FP]
