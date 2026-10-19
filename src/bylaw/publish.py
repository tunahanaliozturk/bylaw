"""Publishes a validated review: one review with the new inline comments, thread changes, the summary."""

from collections.abc import Sequence
from dataclasses import replace
from typing import Protocol

from bylaw.config import Config
from bylaw.github import ReviewComment, SummaryComment
from bylaw.model import ReviewContext, ReviewMemory, ReviewResult
from bylaw.plan import Plan, State, Thread, added_text, group_findings, make_plan
from bylaw.render import inline_body, inline_parts, read_state, review_body, summary_body, tokens_only


class Publisher(Protocol):
    def review_threads(self, repo: str, number: int) -> list[Thread]: ...

    def summary_comment(self, repo: str, number: int) -> SummaryComment | None: ...

    def create_review(
        self, repo: str, number: int, commit_id: str, body: str, comments: Sequence[ReviewComment]
    ) -> None: ...

    def upsert_summary(self, repo: str, number: int, comment_id: int | None, body: str) -> None: ...

    def set_thread_resolved(self, thread_id: str, *, resolved: bool) -> None: ...


def publish(  # noqa: PLR0913 - one call site, every argument is a distinct input
    client: Publisher,
    repo: str,
    number: int,
    *,
    context: ReviewContext,
    result: ReviewResult,
    config: Config,
    memory: ReviewMemory | None = None,
    unreviewed: frozenset[str] = frozenset(),
) -> Plan:
    summary = client.summary_comment(repo, number)
    state = read_state(summary.body) if summary else State(auto_resolved=frozenset())
    threads = client.review_threads(repo, number)
    plan = _plan(context, result, config, threads, state, unreviewed=unreviewed)
    if unread := sum(thread.older_replies_unread for thread in threads):
        note = (
            f"{unread} long review thread(s) read without older replies: the host did not return them, "
            "so a `bylaw: ignore` among them is not seen this run."
        )
        plan = replace(plan, notes=(*plan.notes, note))
    if memory is None and state.review is not None:
        # A run that keeps no memory (bylaw post, no key) still keeps the pull request's token count.
        memory = tokens_only(state.review)
    plan = replace(plan, state=replace(plan.state, review=memory))
    if plan.inline:
        comments = [
            ReviewComment(
                g.finding.file, g.finding.line_end, g.finding.line_start, inline_body(g), inline_parts(g)
            )
            for g in plan.inline
        ]
        client.create_review(repo, number, context.head_sha, review_body(plan), comments)
    done: list[tuple[str, bool]] = []
    try:
        for thread_id, resolved in (
            *((t, True) for t in plan.resolve),
            *((t, False) for t in plan.unresolve),
        ):
            client.set_thread_resolved(thread_id, resolved=resolved)
            done.append((thread_id, resolved))
    except Exception:
        # The summary holds the state of which threads bylaw resolved. Record what really happened before
        # the error goes up, so the next run does not mistake bylaw's own resolves for a maintainer's.
        # The summary counts only the threads really resolved or reopened.
        actual = replace(
            plan,
            state=_state_after(plan, done),
            resolve=tuple(thread_id for thread_id, closed in done if closed),
            unresolve=tuple(thread_id for thread_id, closed in done if not closed),
        )
        body = summary_body(context, result, actual)
        client.upsert_summary(repo, number, summary.id if summary else None, body)
        raise
    client.upsert_summary(repo, number, summary.id if summary else None, summary_body(context, result, plan))
    return plan


def _state_after(plan: Plan, done: Sequence[tuple[str, bool]]) -> State:
    resolved = {thread_id for thread_id, closed in done if closed}
    reopened = {thread_id for thread_id, closed in done if not closed}
    not_resolved = set(plan.resolve) - resolved
    not_reopened = set(plan.unresolve) - reopened
    return State(
        auto_resolved=frozenset((plan.state.auto_resolved - not_resolved) | not_reopened),
        review=plan.state.review,
    )


def first_plan(context: ReviewContext, result: ReviewResult, config: Config) -> Plan:
    """The plan of a run on a pull request with no threads yet: what is posted when nothing was before."""
    return _plan(context, result, config, (), State(auto_resolved=frozenset()))


def preview(context: ReviewContext, result: ReviewResult, config: Config) -> str:
    """What a first run would post, for a terminal with no pull request."""
    plan = first_plan(context, result, config)
    comments = [f"---\n`{g.finding.file}:{g.finding.line_start}`\n\n{inline_body(g)}" for g in plan.inline]
    return "\n\n".join([summary_body(context, result, plan), *comments])


def _plan(  # noqa: PLR0913 - two callers, every argument is a distinct input
    context: ReviewContext,
    result: ReviewResult,
    config: Config,
    threads: Sequence[Thread],
    state: State,
    *,
    unreviewed: frozenset[str] = frozenset(),
) -> Plan:
    groups = group_findings(result.findings, added_text(context))
    return make_plan(
        groups, threads, state, config.severity_threshold, config.max_comments, unreviewed=unreviewed
    )
