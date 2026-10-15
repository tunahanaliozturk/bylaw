"""Publishes a validated review: one review with the new inline comments, thread changes, the summary."""

from collections.abc import Sequence
from typing import Protocol

from bylaw.config import Config
from bylaw.github import ReviewComment, SummaryComment
from bylaw.model import ReviewContext, ReviewResult
from bylaw.plan import Plan, State, Thread, added_text, group_findings, make_plan
from bylaw.render import inline_body, read_state, review_body, summary_body


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
) -> Plan:
    summary = client.summary_comment(repo, number)
    state = read_state(summary.body) if summary else State(auto_resolved=frozenset())
    plan = _plan(context, result, config, client.review_threads(repo, number), state)
    if plan.inline:
        comments = [
            ReviewComment(g.finding.file, g.finding.line_end, g.finding.line_start, inline_body(g))
            for g in plan.inline
        ]
        client.create_review(repo, number, context.head_sha, review_body(plan), comments)
    for thread_id in plan.resolve:
        client.set_thread_resolved(thread_id, resolved=True)
    for thread_id in plan.unresolve:
        client.set_thread_resolved(thread_id, resolved=False)
    client.upsert_summary(repo, number, summary.id if summary else None, summary_body(context, result, plan))
    return plan


def preview(context: ReviewContext, result: ReviewResult, config: Config) -> str:
    """What a first run would post, for a terminal with no pull request."""
    plan = _plan(context, result, config, (), State(auto_resolved=frozenset()))
    comments = [f"---\n`{g.finding.file}:{g.finding.line_start}`\n\n{inline_body(g)}" for g in plan.inline]
    return "\n\n".join([summary_body(context, result, plan), *comments])


def _plan(
    context: ReviewContext, result: ReviewResult, config: Config, threads: Sequence[Thread], state: State
) -> Plan:
    groups = group_findings(result.findings, added_text(context))
    return make_plan(groups, threads, state, config.severity_threshold, config.max_comments)
