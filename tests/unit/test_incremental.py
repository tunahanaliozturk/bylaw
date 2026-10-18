from bylaw.engine import ReviewError, Usage
from bylaw.incremental import file_key, inputs_key, run_model_review
from bylaw.model import (
    AddedLine,
    Category,
    ChangedFile,
    Criterion,
    CriterionResult,
    CriterionStatus,
    Finding,
    Location,
    Requirement,
    ReviewContext,
    ReviewMemory,
    ReviewResult,
    Severity,
)


def _file(path: str, text: str) -> ChangedFile:
    return ChangedFile(
        path=path,
        status="added",
        added_lines=(AddedLine(number=1, text=text),),
        patch=f"@@ -0,0 +1 @@\n+{text}\n",
    )


def _context(*files: ChangedFile, head: str = "h2") -> ReviewContext:
    return ReviewContext(
        base_sha="b",
        head_sha=head,
        title="t",
        files=files,
        rules=(),
        requirements=(
            Requirement(
                source="#1", title="Login", text="", criteria=(Criterion(key="AC-1", text="Log in"),)
            ),
        ),
        findings=(),
        notes=(),
    )


def _finding(path: str, message: str) -> Finding:
    return Finding(
        file=path,
        line_start=1,
        line_end=1,
        category=Category.BUG,
        severity=Severity.HIGH,
        message=message,
    )


class FakeReviewer:
    def __init__(self, result: ReviewResult | None = None, *, error: str | None = None) -> None:
        self.result = result or ReviewResult()
        self.error = error
        self.inputs: list[str] = []
        self.last_usage: Usage | None = None

    def review(self, system: str, user: str) -> ReviewResult:
        self.inputs.append(user)
        self.last_usage = Usage(input_tokens=1000, output_tokens=200)
        if self.error:
            raise ReviewError(self.error)
        return self.result


OLD = _file("old.py", "a = 1")
NEW = _file("new.py", "b = 2")
MET = CriterionResult(
    criterion="#1/AC-1", status=CriterionStatus.MET, code=(Location(file="old.py", line=1),)
)


def _memory(context: ReviewContext, **changes: object) -> ReviewMemory:
    base = ReviewMemory(
        head_sha="h1",
        inputs=inputs_key(context),
        files={"old.py": file_key(OLD)},
        findings=(_finding("old.py", "Old problem."),),
        criteria=(MET,),
        criteria_since={"#1/AC-1": "h1"},
        tokens=5000,
    )
    return base.model_copy(update=changes)


def test_only_files_changed_since_the_last_run_go_to_the_model() -> None:
    context = _context(OLD, NEW)
    reviewer = FakeReviewer(ReviewResult(findings=(_finding("new.py", "New problem."),)))

    run = run_model_review(context, lambda: reviewer, _memory(context), incremental=True, budget=None)

    assert len(reviewer.inputs) == 1
    assert "new.py" in reviewer.inputs[0] and "a = 1" not in reviewer.inputs[0]
    assert sorted(f.message for f in run.result.findings) == ["New problem.", "Old problem."]
    assert any("1 changed file(s)" in note and "1 unchanged" in note for note in run.notes)


def test_a_met_criterion_whose_code_did_not_change_keeps_its_status_and_says_since_when() -> None:
    context = _context(OLD, NEW)
    reviewer = FakeReviewer(
        ReviewResult(criteria=(CriterionResult(criterion="#1/AC-1", status=CriterionStatus.MISSING),))
    )

    run = run_model_review(context, lambda: reviewer, _memory(context), incremental=True, budget=None)

    (criterion,) = run.result.criteria
    assert criterion.status is CriterionStatus.MET
    assert "assessed on h1" in criterion.note
    assert run.memory is not None and run.memory.criteria_since == {"#1/AC-1": "h1"}


def test_a_partial_criterion_is_assessed_again() -> None:
    context = _context(OLD, NEW)
    partial = MET.model_copy(update={"status": CriterionStatus.PARTIAL})
    fresh = CriterionResult(
        criterion="#1/AC-1", status=CriterionStatus.MET, code=(Location(file="new.py", line=1),)
    )

    run = run_model_review(
        context,
        lambda: FakeReviewer(ReviewResult(criteria=(fresh,))),
        _memory(context, criteria=(partial,)),
        incremental=True,
        budget=None,
    )

    assert run.result.criteria == (fresh,)
    assert run.memory is not None and run.memory.criteria_since == {"#1/AC-1": "h2"}


def test_a_changed_file_is_reviewed_again_and_loses_its_old_findings() -> None:
    edited = _file("old.py", "a = 2")
    context = _context(edited)
    reviewer = FakeReviewer()

    run = run_model_review(context, lambda: reviewer, _memory(context), incremental=True, budget=None)

    assert "a = 2" in reviewer.inputs[0]
    assert run.result.findings == ()


def test_changed_rules_or_requirements_mean_a_full_review() -> None:
    context = _context(OLD, NEW)
    stale = _memory(context, inputs="something else")
    reviewer = FakeReviewer()

    run = run_model_review(context, lambda: reviewer, stale, incremental=True, budget=None)

    assert "a = 1" in reviewer.inputs[0] and "b = 2" in reviewer.inputs[0]
    assert run.result.findings == ()


def test_incremental_off_reviews_everything_but_still_counts_tokens() -> None:
    context = _context(OLD, NEW)
    reviewer = FakeReviewer()

    run = run_model_review(context, lambda: reviewer, _memory(context), incremental=False, budget=None)

    assert "a = 1" in reviewer.inputs[0]
    assert run.memory is not None and (run.memory.run_tokens, run.memory.tokens) == (1200, 6200)


def test_with_nothing_changed_since_the_last_run_the_model_is_not_called() -> None:
    context = _context(OLD)
    reviewer = FakeReviewer()

    run = run_model_review(context, lambda: reviewer, _memory(context), incremental=True, budget=None)

    assert reviewer.inputs == []
    assert [f.message for f in run.result.findings] == ["Old problem."]
    assert run.memory is not None and run.memory.run_tokens == 0


def test_a_file_left_out_for_size_is_not_remembered_as_reviewed() -> None:
    big = ChangedFile(
        path="big.py",
        status="added",
        added_lines=(AddedLine(number=1, text="x" * 50_000),),
        patch="@@ -0,0 +1 @@\n+" + "x" * 50_000 + "\n",
    )
    context = _context(NEW, big).model_copy(update={"input_tokens": 10_000})

    run = run_model_review(context, FakeReviewer, None, incremental=True, budget=None)

    assert run.memory is not None
    assert set(run.memory.files) == {"new.py"}


def test_the_token_budget_stops_the_model_and_keeps_the_earlier_review() -> None:
    context = _context(OLD, NEW)
    reviewer = FakeReviewer()

    run = run_model_review(context, lambda: reviewer, _memory(context), incremental=True, budget=5000)

    assert reviewer.inputs == []
    assert [f.message for f in run.result.findings] == ["Old problem."]
    assert any("token budget" in note and "5,000 of 5,000" in note for note in run.notes)
    assert run.memory == _memory(context).model_copy(update={"run_tokens": 0})


def test_a_model_failure_keeps_the_earlier_review_instead_of_resolving_it() -> None:
    context = _context(OLD, NEW)

    run = run_model_review(
        context, lambda: FakeReviewer(error="overloaded"), _memory(context), incremental=True, budget=None
    )

    assert [f.message for f in run.result.findings] == ["Old problem."]
    assert any("did not run: overloaded" in note for note in run.notes)
    # A failed call can still be billed, so it counts against the budget; nothing else in memory moves.
    assert run.memory == _memory(context).model_copy(update={"tokens": 6200, "run_tokens": 1200})


def test_without_a_key_no_model_runs_and_nothing_is_remembered() -> None:
    run = run_model_review(_context(NEW), None, None, incremental=True, budget=None)

    assert run.result == ReviewResult()
    assert run.memory is None
    assert run.notes == ("The model review did not run: no API key is set.",)


def test_a_first_run_remembers_what_it_reviewed() -> None:
    context = _context(OLD, NEW, head="h1")
    found = _finding("new.py", "New problem.")

    run = run_model_review(
        context, lambda: FakeReviewer(ReviewResult(findings=(found,))), None, incremental=True, budget=None
    )

    assert run.memory is not None
    assert run.memory.head_sha == "h1"
    assert run.memory.files == {"old.py": file_key(OLD), "new.py": file_key(NEW)}
    assert run.memory.findings == (found,)


def test_a_run_without_a_key_keeps_the_earlier_review_when_there_is_one() -> None:
    context = _context(OLD, NEW)

    run = run_model_review(context, None, _memory(context), incremental=True, budget=None)

    assert [f.message for f in run.result.findings] == ["Old problem."]
    assert run.memory == _memory(context).model_copy(update={"run_tokens": 0})


def test_the_model_is_told_which_files_it_does_not_see() -> None:
    context = _context(OLD, NEW)
    reviewer = FakeReviewer()

    run_model_review(context, lambda: reviewer, _memory(context), incremental=True, budget=None)

    assert 'kind="unchanged_files"' in reviewer.inputs[0]
    assert "old.py" in reviewer.inputs[0]


def test_a_reviewer_that_cannot_be_built_leaves_a_note() -> None:
    def broken() -> FakeReviewer:
        raise ReviewError("--model is required with the openai provider")

    run = run_model_review(_context(NEW), broken, None, incremental=True, budget=None)

    assert run.notes == ("The model review did not run: --model is required with the openai provider.",)


def test_a_run_without_the_model_keeps_findings_only_for_unchanged_files() -> None:
    edited = _file("old.py", "a = 2")
    context = _context(edited, NEW)
    memory = _memory(context, files={"old.py": file_key(OLD), "new.py": file_key(NEW)})
    memory = memory.model_copy(update={"findings": (*memory.findings, _finding("new.py", "New problem."))})

    run = run_model_review(context, None, memory, incremental=True, budget=None)

    assert [f.message for f in run.result.findings] == ["New problem."]
    assert run.unreviewed == frozenset({"old.py"})


def test_a_run_with_nothing_new_keeps_every_criterion() -> None:
    context = _context(OLD)
    missing = CriterionResult(criterion="#1/AC-2", status=CriterionStatus.MISSING)
    memory = _memory(context, criteria=(MET, missing), criteria_since={"#1/AC-1": "h1", "#1/AC-2": "h1"})

    run = run_model_review(context, FakeReviewer, memory, incremental=True, budget=None)

    assert [(c.criterion, c.status) for c in run.result.criteria] == [
        ("#1/AC-1", CriterionStatus.MET),
        ("#1/AC-2", CriterionStatus.MISSING),
    ]
    assert run.memory is not None and len(run.memory.criteria) == 2


def test_a_met_inferred_criterion_is_derived_again_rather_than_carried() -> None:
    context = _context(OLD, NEW)
    inferred = MET.model_copy(update={"criterion": "#1/IC-1", "text": "Log failed logins"})
    fresh = CriterionResult(criterion="#1/IC-1", text="Rate limit logins", status=CriterionStatus.MISSING)

    run = run_model_review(
        context,
        lambda: FakeReviewer(ReviewResult(criteria=(fresh,))),
        _memory(context, criteria=(inferred,)),
        incremental=True,
        budget=None,
    )

    assert run.result.criteria == (fresh,)


def test_a_model_finding_on_a_file_it_was_not_shown_is_dropped() -> None:
    context = _context(OLD, NEW)
    stray = _finding("old.py", "Guessed problem.")

    run = run_model_review(
        context,
        lambda: FakeReviewer(ReviewResult(findings=(stray,))),
        _memory(context),
        incremental=True,
        budget=None,
    )

    assert [f.message for f in run.result.findings] == ["Old problem."]


def test_the_incremental_note_is_left_out_when_the_model_fails() -> None:
    context = _context(OLD, NEW)

    run = run_model_review(
        context, lambda: FakeReviewer(error="overloaded"), _memory(context), incremental=True, budget=None
    )

    assert not any(note.startswith("Incremental review") for note in run.notes)


def test_a_kept_criterion_names_the_commit_it_was_assessed_on() -> None:
    context = _context(OLD, NEW)
    memory = _memory(context, head_sha="h9", criteria_since={"#1/AC-1": "h1"})

    run = run_model_review(context, FakeReviewer, memory, incremental=True, budget=None)

    assert "assessed on h1" in run.result.criteria[0].note


def test_the_input_is_cut_to_what_is_left_of_the_budget() -> None:
    context = _context(OLD, NEW)
    reviewer = FakeReviewer()

    run = run_model_review(context, lambda: reviewer, _memory(context), incremental=True, budget=5100)

    assert reviewer.inputs == []
    assert run.unreviewed == frozenset({"new.py"})
    assert any("token budget" in note for note in run.notes)


def test_findings_validation_dropped_are_not_remembered() -> None:
    from bylaw.incremental import keep_valid  # noqa: PLC0415

    memory = _memory(_context(OLD))
    kept = keep_valid(memory, ())

    assert kept is not None and kept.findings == ()
    assert keep_valid(None, ()) is None


def _private(context: ReviewContext) -> ReviewContext:
    item = Requirement(source="PROJ-1", title="Secret plan", text="Secret text", criteria=(), quoted=False)
    return context.model_copy(update={"requirements": (*context.requirements, item)})


PRIVATE_ANSWER = ReviewResult(
    criteria=(
        CriterionResult(
            criterion="PROJ-1/IC-1", status=CriterionStatus.MET, text="Secret rule", note="Secret"
        ),
        CriterionResult(criterion="#1/AC-1", status=CriterionStatus.PARTIAL, note="Public note"),
    )
)


def test_the_memory_keeps_no_text_or_note_of_a_work_item_kept_out_of_quotes() -> None:
    context = _private(_context(OLD, NEW, head="h1"))

    run = run_model_review(context, lambda: FakeReviewer(PRIVATE_ANSWER), None, incremental=True, budget=None)

    assert run.memory is not None
    remembered = {c.criterion: c for c in run.memory.criteria}
    assert (remembered["PROJ-1/IC-1"].text, remembered["PROJ-1/IC-1"].note) == (None, "")
    assert remembered["#1/AC-1"].note == "Public note"
    assert "Secret" not in run.memory.model_dump_json()


def test_an_earlier_memory_loses_the_text_of_a_work_item_now_kept_out_of_quotes() -> None:
    context = _private(_context(OLD, NEW))
    earlier = _memory(context, criteria=PRIVATE_ANSWER.criteria)

    run = run_model_review(context, None, earlier, incremental=True, budget=None)

    assert run.memory is not None
    assert "Secret" not in run.memory.model_dump_json()
