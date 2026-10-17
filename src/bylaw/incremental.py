"""Runs the model review, and on a new push reviews only the files that changed since the last run.

The memory of the last run travels in the summary comment's state (ADR 0005), and is read only from a
summary a bot wrote (ADR 0012). A file counts as unchanged when its change against the base is the same
as last time, compared by hash, so a rebase or force push that keeps a file's change keeps its review and
anything else is reviewed again. Rules, requirements or a new bylaw version mean a full review.
"""

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass, field
from importlib.metadata import version

from bylaw.engine import Reviewer, ReviewError, Usage
from bylaw.github import SummaryComment
from bylaw.model import (
    ChangedFile,
    CriterionResult,
    CriterionStatus,
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


def trusted_memory(summary: SummaryComment | None) -> ReviewMemory | None:
    """The memory decides what the model skips, so only a summary a bot wrote may carry it (ADR 0012)."""
    if summary is None or not summary.bot:
        return None
    return read_state(summary.body).review


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
        return _held(memory, ["The model review did not run: no API key is set."], 0)
    spent = memory.tokens if memory else 0
    if budget is not None and spent >= budget:
        note = (
            f"The model review did not run: this pull request reached its token budget ({spent:,} of "
            f"{budget:,} tokens, `[budget] pr_tokens` in .bylaw.toml). The earlier review stands."
        )
        return _held(memory, [note], 0)

    plan = _plan(context, memory) if incremental else None
    notes: list[str] = []
    target = context
    if plan is not None:
        target = context.model_copy(
            update={
                "files": tuple(f for f in context.files if f.path in plan.changed),
                "findings": tuple(f for f in context.findings if f.file in plan.changed),
                "carried_over": tuple(sorted(plan.carried)),
            }
        )
        notes.append(
            f"Incremental review: {len(plan.changed)} changed file(s) since {plan.since[:7]} reviewed, "
            f"{len(plan.carried)} unchanged file(s) kept their earlier findings."
        )
    reviewable = [f for f in target.files if f.status != "removed" and f.patch]
    if plan is not None and not reviewable:
        kept = _merge(plan, ReviewResult())
        return ModelRun(
            kept, _remember(context, ReviewResult(), plan, memory, read=frozenset(), used=0), tuple(notes)
        )

    text, left_out = render_input(target)
    if left_out:
        notes.append(f"Left out of the model review for size: {', '.join(left_out)}.")
    reviewer: Reviewer | None = None
    try:
        reviewer = make_reviewer()
        result = reviewer.review(system_prompt(), text)
    except ReviewError as error:
        notes.append(f"The model review did not run: {error}.")
        # A failed call can still be billed, so it counts against the budget.
        return _held(memory, notes, _tokens(getattr(reviewer, "last_usage", None)))
    used = _tokens(getattr(reviewer, "last_usage", None))
    read = frozenset(f.path for f in reviewable if f.path not in left_out)
    if plan is None:
        merged = result
        plan = _Plan(changed=frozenset(f.path for f in context.files), carried=frozenset(), since="")
    else:
        merged = _merge(plan, result)
    return ModelRun(merged, _remember(context, result, plan, memory, read=read, used=used), tuple(notes))


@dataclass(frozen=True, slots=True)
class _Plan:
    changed: frozenset[str]
    carried: frozenset[str]
    since: str
    kept: ReviewResult = field(default_factory=ReviewResult)


def _plan(context: ReviewContext, memory: ReviewMemory | None) -> _Plan | None:
    if memory is None or memory.inputs != inputs_key(context):
        return None
    carried = frozenset(f.path for f in context.files if memory.files.get(f.path) == file_key(f))
    if not carried:
        return None
    changed = frozenset(f.path for f in context.files) - carried
    kept = ReviewResult(
        findings=tuple(f for f in memory.findings if f.file in carried),
        criteria=tuple(c for c in memory.criteria if _stands(c, carried)),
        scope_creep=tuple(s for s in memory.scope_creep if s.file in carried),
    )
    return _Plan(changed=changed, carried=carried, since=memory.head_sha, kept=kept)


def _stands(criterion: CriterionResult, carried: frozenset[str]) -> bool:
    """A met criterion stands while every file it was met in is unchanged; anything else is asked again."""
    places = (*criterion.code, *criterion.tests)
    return criterion.status is CriterionStatus.MET and bool(places) and all(p.file in carried for p in places)


def _merge(plan: _Plan, result: ReviewResult) -> ReviewResult:
    kept_keys = {c.criterion for c in plan.kept.criteria}
    since = f"unchanged since {plan.since[:7]}"
    kept_criteria = tuple(
        c.model_copy(update={"note": f"{c.note}; {since}" if c.note else since}) for c in plan.kept.criteria
    )
    return ReviewResult(
        findings=(*result.findings, *plan.kept.findings),
        criteria=(*kept_criteria, *(c for c in result.criteria if c.criterion not in kept_keys)),
        scope_creep=(*result.scope_creep, *plan.kept.scope_creep),
    )


def _remember(  # noqa: PLR0913 - one caller, every argument is a distinct input
    context: ReviewContext,
    fresh: ReviewResult,
    plan: _Plan,
    memory: ReviewMemory | None,
    *,
    read: frozenset[str],
    used: int,
) -> ReviewMemory:
    kept_keys = {c.criterion for c in plan.kept.criteria}
    earlier_since = memory.criteria_since if memory else {}
    criteria = (*plan.kept.criteria, *(c for c in fresh.criteria if c.criterion not in kept_keys))
    since = {
        c.criterion: earlier_since.get(c.criterion, plan.since)
        if c.criterion in kept_keys
        else context.head_sha
        for c in criteria
    }
    keys = {f.path: file_key(f) for f in context.files}
    return ReviewMemory(
        head_sha=context.head_sha,
        inputs=inputs_key(context),
        files={path: keys[path] for path in sorted(plan.carried | read)},
        findings=(*fresh.findings, *plan.kept.findings),
        criteria=criteria,
        scope_creep=(*fresh.scope_creep, *plan.kept.scope_creep),
        criteria_since=since,
        tokens=(memory.tokens if memory else 0) + used,
        run_tokens=used,
    )


def _held(memory: ReviewMemory | None, notes: list[str], used: int) -> ModelRun:
    """A run where the model did not answer: the last review's answers stand, so nothing is resolved as
    fixed for want of a model. Validation still drops any that no longer fit the code."""
    if memory is None:
        return ModelRun(ReviewResult(), None, tuple(notes))
    earlier = ReviewResult(findings=memory.findings, criteria=memory.criteria, scope_creep=memory.scope_creep)
    kept = memory.model_copy(update={"tokens": memory.tokens + used, "run_tokens": used})
    return ModelRun(earlier, kept, tuple(notes))


def _tokens(usage: Usage | None) -> int:
    return usage.input_tokens + usage.output_tokens if usage else 0


def _hash(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
