"""Runs the model review, and on a new push reviews only the files that changed since the last run.

The memory of the last run travels in the summary comment's state (ADR 0005), and is read only from a
summary a bot wrote (ADR 0012). A file counts as unchanged when its change against the base is the same
as last time, compared by hash, so a rebase or force push that keeps a file's change keeps its review and
anything else is reviewed again. Rules, requirements or a new bylaw version mean a full review.
"""

import hashlib
import json
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from importlib.metadata import version

from bylaw.engine import Reviewer, ReviewError, Usage
from bylaw.github import SummaryComment
from bylaw.model import (
    ChangedFile,
    CriterionResult,
    CriterionStatus,
    Finding,
    ReviewContext,
    ReviewMemory,
    ReviewResult,
)
from bylaw.prompt import render_input, system_prompt
from bylaw.render import read_state


@dataclass(frozen=True, slots=True)
class ModelRun:
    result: ReviewResult
    memory: ReviewMemory | None
    notes: tuple[str, ...]
    # Changed files the model did not read this run: their threads are neither resolved nor posted again.
    unreviewed: frozenset[str] = frozenset()


def trusted_memory(summary: SummaryComment | None) -> ReviewMemory | None:
    """The memory decides what the model skips, so only a summary a bot wrote may carry it (ADR 0012)."""
    if summary is None or not summary.bot:
        return None
    return read_state(summary.body).review


def keep_valid(memory: ReviewMemory | None, findings: Iterable[Finding]) -> ReviewMemory | None:
    """Remember only the findings that passed validation, so the memory does not carry what was dropped."""
    if memory is None:
        return None
    valid = set(findings)
    return memory.model_copy(update={"findings": tuple(f for f in memory.findings if f in valid)})


def file_key(file: ChangedFile) -> str:
    raw = json.dumps(
        [file.status, file.previous_path, file.patch, file.patch_omitted, file.missing_final_newline]
    )
    return _hash(raw)


def inputs_key(context: ReviewContext) -> str:
    """What every file is reviewed against; when it changes, earlier answers no longer hold."""
    rules = [[rule.path, rule.kind, rule.text] for rule in context.rules]
    requirements = [requirement.model_dump(mode="json") for requirement in context.requirements]
    return _hash(json.dumps([version("bylaw"), rules, requirements]))


def run_model_review(
    context: ReviewContext,
    make_reviewer: Callable[[], Reviewer] | None,
    memory: ReviewMemory | None,
    *,
    incremental: bool,
    budget: int | None,
) -> ModelRun:
    """The model's result for the whole change, with the earlier run's answers for unchanged files."""
    if make_reviewer is None:
        return _held(context, memory, ["The model review did not run: no API key is set."], 0)
    spent = memory.tokens if memory else 0
    if budget is not None and spent >= budget:
        return _held(context, memory, [_over_budget(spent, budget)], 0)

    plan = _plan(context, memory if incremental else None)
    room = context.input_tokens if budget is None else min(context.input_tokens, budget - spent)
    target = context.model_copy(
        update={
            "files": tuple(f for f in context.files if f.path not in plan.carried),
            "findings": tuple(f for f in context.findings if f.file not in plan.carried),
            "carried_over": tuple(sorted(plan.carried)),
            "input_tokens": room,
        }
    )
    reviewable = [f.path for f in target.files if f.status != "removed" and f.patch]
    if not reviewable:
        # Nothing new to read: the earlier review stands whole, criteria included.
        merged, criteria = _merge(context, plan, ReviewResult(), asked=False)
        remembered = _remember(context, plan, ReviewResult(), criteria, spent=spent, used=0)
        return ModelRun(merged, remembered, _incremental(plan, 0))

    text, left_out = render_input(target)
    read = frozenset(reviewable) - frozenset(left_out)
    if not read:
        if room < context.input_tokens:
            note = (
                f"The model review did not run: the token budget (`[budget] pr_tokens`) leaves {room:,} "
                "tokens, too few for any changed file. The earlier review stands."
            )
        else:
            note = "The model review did not run: no changed file fits in the input budget."
        return _held(context, memory, [note], 0)
    notes = list(_incremental(plan, len(read)))
    if left_out:
        notes.append(f"Left out of the model review for size: {', '.join(left_out)}.")
    reviewer: Reviewer | None = None
    try:
        reviewer = make_reviewer()
        answer = reviewer.review(system_prompt(), text)
    except ReviewError as error:
        # A failed call can still be billed, so it counts against the budget.
        used = _tokens(getattr(reviewer, "last_usage", None))
        return _held(context, memory, [f"The model review did not run: {error}."], used)
    fresh = ReviewResult(
        findings=tuple(f for f in answer.findings if f.file in read),
        criteria=answer.criteria,
        scope_creep=tuple(s for s in answer.scope_creep if s.file in read),
    )
    used = _tokens(getattr(reviewer, "last_usage", None))
    merged, criteria = _merge(context, plan, fresh, asked=True)
    memory_after = _remember(context, plan, fresh, criteria, spent=spent, used=used, read=read)
    return ModelRun(merged, memory_after, tuple(notes), unreviewed=frozenset(left_out))


@dataclass(frozen=True, slots=True)
class _Plan:
    carried: frozenset[str]
    memory: ReviewMemory | None


def _plan(context: ReviewContext, memory: ReviewMemory | None) -> _Plan:
    """Which files keep their earlier review; none when there is no usable memory."""
    if memory is None or memory.inputs != inputs_key(context):
        return _Plan(carried=frozenset(), memory=None)
    carried = frozenset(f.path for f in context.files if memory.files.get(f.path) == file_key(f))
    return _Plan(carried=carried, memory=memory if carried else None)


def _incremental(plan: _Plan, read: int) -> tuple[str, ...]:
    if plan.memory is None:
        return ()
    return (
        f"Incremental review: {read} changed file(s) since {plan.memory.head_sha[:7]} reviewed, "
        f"{len(plan.carried)} unchanged file(s) kept their earlier findings.",
    )


def _merge(
    context: ReviewContext, plan: _Plan, fresh: ReviewResult, *, asked: bool
) -> tuple[ReviewResult, tuple[tuple[CriterionResult, str], ...]]:
    """The result to publish, and each criterion as last assessed with the commit it was assessed on."""
    criteria = _criteria(context, plan, fresh, asked=asked)
    shown = tuple(_dated(c, since, context.head_sha) for c, since in criteria)
    earlier = plan.memory
    if earlier is None:
        return ReviewResult(findings=fresh.findings, criteria=shown, scope_creep=fresh.scope_creep), criteria
    return (
        ReviewResult(
            findings=(*fresh.findings, *(f for f in earlier.findings if f.file in plan.carried)),
            criteria=shown,
            scope_creep=(*fresh.scope_creep, *(s for s in earlier.scope_creep if s.file in plan.carried)),
        ),
        criteria,
    )


def _criteria(
    context: ReviewContext, plan: _Plan, fresh: ReviewResult, *, asked: bool
) -> tuple[tuple[CriterionResult, str], ...]:
    earlier = plan.memory
    now = [(c, context.head_sha) for c in fresh.criteria]
    if earlier is None:
        return tuple(now)

    def since(c: CriterionResult) -> str:
        return earlier.criteria_since.get(c.criterion, earlier.head_sha)

    if not asked:
        return tuple((c, since(c)) for c in earlier.criteria)
    kept = [(c, since(c)) for c in earlier.criteria if _stands(c, plan.carried)]
    taken = {c.criterion for c, _ in kept}
    now = [(c, s) for c, s in now if c.criterion not in taken]
    taken |= {c.criterion for c, _ in now}
    # A listed criterion the model left unanswered keeps its last answer; inferred ones are derived anew.
    unanswered = [
        (c, since(c)) for c in earlier.criteria if c.criterion not in taken and not _inferred(c.criterion)
    ]
    return (*kept, *now, *unanswered)


def _stands(criterion: CriterionResult, carried: frozenset[str]) -> bool:
    """A met criterion stands while every file it was met in is unchanged; anything else is asked again.

    Inferred criteria (ADR 0011) are numbered afresh on every run, so a label may name another criterion.
    """
    places = (*criterion.code, *criterion.tests)
    return (
        criterion.status is CriterionStatus.MET
        and not _inferred(criterion.criterion)
        and bool(places)
        and all(p.file in carried for p in places)
    )


def _inferred(key: str) -> bool:
    return "/IC-" in key


def _dated(criterion: CriterionResult, since: str, head: str) -> CriterionResult:
    if since == head:
        return criterion
    when = f"assessed on {since[:7]}"
    return criterion.model_copy(update={"note": f"{criterion.note}; {when}" if criterion.note else when})


def _remember(  # noqa: PLR0913 - two callers, every argument is a distinct input
    context: ReviewContext,
    plan: _Plan,
    fresh: ReviewResult,
    criteria: tuple[tuple[CriterionResult, str], ...],
    *,
    spent: int,
    used: int,
    read: frozenset[str] = frozenset(),
) -> ReviewMemory:
    earlier = plan.memory
    keys = {f.path: file_key(f) for f in context.files}
    carried_findings = tuple(f for f in earlier.findings if f.file in plan.carried) if earlier else ()
    carried_creep = tuple(s for s in earlier.scope_creep if s.file in plan.carried) if earlier else ()
    return ReviewMemory(
        head_sha=context.head_sha,
        inputs=inputs_key(context),
        files={path: keys[path] for path in sorted(plan.carried | read)},
        findings=(*fresh.findings, *carried_findings),
        criteria=_unquoted(context, tuple(c for c, _ in criteria)),
        scope_creep=(*fresh.scope_creep, *carried_creep),
        criteria_since={c.criterion: since for c, since in criteria},
        tokens=spent + used,
        run_tokens=used,
    )


def _held(context: ReviewContext, memory: ReviewMemory | None, notes: list[str], used: int) -> ModelRun:
    """A run where the model did not answer: the last review stands for unchanged files, and the threads
    on changed files are left as they are, so nothing is resolved as fixed or posted again for want of a
    model. Without a memory there is nothing to keep."""
    if memory is None:
        return ModelRun(ReviewResult(), None, tuple(notes))
    keys = {f.path: file_key(f) for f in context.files}
    same = frozenset(path for path, key in keys.items() if memory.files.get(path) == key)
    earlier = ReviewResult(
        findings=tuple(f for f in memory.findings if f.file in same),
        criteria=memory.criteria,
        scope_creep=tuple(s for s in memory.scope_creep if s.file in same),
    )
    kept = memory.model_copy(
        update={
            "tokens": memory.tokens + used,
            "run_tokens": used,
            "criteria": _unquoted(context, memory.criteria),
        }
    )
    return ModelRun(earlier, kept, tuple(notes), unreviewed=frozenset(keys) - same)


def _unquoted(context: ReviewContext, criteria: tuple[CriterionResult, ...]) -> tuple[CriterionResult, ...]:
    """The memory sits in the public summary, so a work item kept out of quotes leaves its inferred
    criterion text and the reviewer's notes out of it too (ADR 0014). Keys and status are enough to carry."""
    private = {r.source for r in context.requirements if not r.quoted}
    return tuple(
        c.model_copy(update={"text": None, "note": ""}) if c.criterion.rpartition("/")[0] in private else c
        for c in criteria
    )


def _over_budget(spent: int, budget: int) -> str:
    return (
        f"The model review did not run: this pull request reached its token budget ({spent:,} of "
        f"{budget:,} tokens, `[budget] pr_tokens` in .bylaw.toml). The earlier review stands."
    )


def _tokens(usage: Usage | None) -> int:
    return usage.input_tokens + usage.output_tokens if usage else 0


def _hash(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
