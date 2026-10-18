"""One pull request reviewed end to end. `bylaw review --pr` and the GitHub App run this same flow."""

from collections.abc import Callable, Mapping

from bylaw.config import Config, load_config
from bylaw.context import build_context
from bylaw.engine import Reviewer
from bylaw.github import GitHubClient, GitHubSource
from bylaw.incremental import ModelRun, keep_valid, run_model_review, trusted_memory
from bylaw.model import Finding, ReviewContext, ReviewMemory, ReviewResult
from bylaw.plan import remaining
from bylaw.publish import publish
from bylaw.validate import Validated, validate

Say = Callable[[str], None]
MakeReviewer = Callable[[], Reviewer] | None


def review_pull_request(  # noqa: PLR0913 - two callers, every argument is a distinct input
    client: GitHubClient,
    repo: str,
    number: int,
    *,
    make: MakeReviewer,
    post: bool,
    say: Say,
    defaults: str | None = None,
    env: Mapping[str, str] | None = None,
) -> tuple[Validated, tuple[Finding, ...]]:
    """Review a pull request; also return the findings `--fail-on` counts (muted ones excluded).

    `make` builds the model reviewer, None for the deterministic checks only. `defaults` is the
    organisation's `.bylaw.toml` (ADR 0017) and `env` holds the tracker tokens (ADR 0014).
    """
    source = GitHubSource(client, repo, number)
    config = load_config(source.read_base(".bylaw.toml"), defaults)
    context = build_context(source, env, config)
    memory = trusted_memory(client.summary_comment(repo, number))
    context, run = with_model_review(context, make, say, config, memory)
    checked = check(context, run.result, say)
    if not post:
        return checked, checked.result.findings
    plan = publish(
        client,
        repo,
        number,
        context=context,
        result=checked.result,
        config=config,
        memory=keep_valid(run.memory, checked.result.findings),
        unreviewed=run.unreviewed,
    )
    say(f"posted {len(plan.inline)} comment(s), resolved {len(plan.resolve)}.")
    return checked, remaining(plan)


def with_model_review(
    context: ReviewContext,
    make: MakeReviewer,
    say: Say,
    config: Config | None = None,
    memory: ReviewMemory | None = None,
) -> tuple[ReviewContext, ModelRun]:
    """The context with notes about the model run, the model's result and what to remember for next time."""
    settings = config or Config()
    run = run_model_review(
        context, make, memory, incremental=settings.incremental, budget=settings.budget.pr_tokens
    )
    for note in run.notes:
        say(note)
    return context.model_copy(update={"notes": (*context.notes, *run.notes)}), run


def check(context: ReviewContext, result: ReviewResult, say: Say) -> Validated:
    merged = result.model_copy(update={"findings": (*context.findings, *result.findings)})
    checked = validate(context, merged)
    for reason in checked.dropped:
        say(f"dropped {reason}")
    return checked
