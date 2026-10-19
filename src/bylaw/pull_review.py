"""One pull request reviewed end to end. `bylaw review --pr` and the GitHub App run this same flow, and
`bylaw review --gitlab-mr` runs its second half for a GitLab merge request (ADR 0020)."""

from collections.abc import Callable, Mapping
from dataclasses import dataclass

from bylaw.config import Budget, Config, load_config
from bylaw.context import build_context
from bylaw.engine import Reviewer
from bylaw.github import TRUSTED_ASSOCIATIONS, GitHubClient, GitHubSource, PullRequest
from bylaw.incremental import ModelRun, keep_valid, run_model_review, trusted_memory
from bylaw.model import MODEL_NOT_RUN, Finding, ReviewContext, ReviewMemory, ReviewResult
from bylaw.plan import Plan, remaining
from bylaw.publish import Publisher, first_plan, publish
from bylaw.source import RepoSource
from bylaw.validate import Validated, validate

Say = Callable[[str], None]
MakeReviewer = Callable[[], Reviewer] | None


@dataclass(frozen=True, slots=True)
class PullReview:
    checked: Validated
    # The findings `--fail-on` counts: muted ones excluded once published.
    counted: tuple[Finding, ...]
    # The head commit the review read, which may be newer than the one an event named.
    head_sha: str
    # What was reviewed and what was posted, or would be on a first run: the evidence record (ADR 0021).
    context: ReviewContext
    plan: Plan


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
    shared_secrets: bool = False,
    operator_sites: bool = False,
) -> PullReview:
    """Review a pull request.

    `make` builds the model reviewer, None for the deterministic checks only. `defaults` is the
    organisation's `.bylaw.toml` (ADR 0017) and `env` holds the tracker tokens (ADR 0014).
    `shared_secrets`: the keys and tokens belong to a GitHub App installation, not to this repository, so
    the repository's settings cannot say where they go (ADR 0017). `operator_sites` alone pins only the
    tracker sites, for a repository the caller picked that is not its own (ADR 0019).
    """
    source = GitHubSource(client, repo, number)
    config = load_config(source.read_base(".bylaw.toml"), defaults)
    skipped = None
    if shared_secrets:
        config = with_app_budget(config)
        if make is not None and (skipped := model_gate(source.pull_request(), config)):
            make = None
    return review_change(
        source,
        client,
        repo,
        number,
        config,
        make=make,
        post=post,
        say=say,
        env=env,
        operator_sites=shared_secrets or operator_sites,
        skipped=skipped,
    )


def review_change(  # noqa: PLR0913 - every argument is a distinct input
    source: RepoSource,
    publisher: Publisher,
    repo: str,
    number: int,
    config: Config,
    *,
    make: MakeReviewer,
    post: bool,
    say: Say,
    env: Mapping[str, str] | None = None,
    operator_sites: bool = False,
    skipped: str | None = None,
) -> PullReview:
    """Review a change with its base branch configuration, and publish it when `post` is set. The host
    differs only in `source` and `publisher`, which for a GitLab merge request are one object."""
    context = build_context(source, env, config, operator_sites=operator_sites)
    memory = trusted_memory(publisher.summary_comment(repo, number))
    context, run = with_model_review(context, make, say, config, memory, skipped=skipped)
    checked = check(context, run.result, say)
    if not post:
        plan = first_plan(context, checked.result, config)
        return PullReview(checked, remaining(plan), context.head_sha, context, plan)
    plan = publish(
        publisher,
        repo,
        number,
        context=context,
        result=checked.result,
        config=config,
        memory=keep_valid(run.memory, checked.result.findings),
        unreviewed=run.unreviewed,
    )
    say(f"posted {len(plan.inline)} comment(s), resolved {len(plan.resolve)}.")
    return PullReview(checked, remaining(plan), context.head_sha, context, plan)


def with_model_review(  # noqa: PLR0913 - every argument is a distinct input
    context: ReviewContext,
    make: MakeReviewer,
    say: Say,
    config: Config | None = None,
    memory: ReviewMemory | None = None,
    *,
    skipped: str | None = None,
) -> tuple[ReviewContext, ModelRun]:
    """The context with notes about the model run, the model's result and what to remember for next time."""
    settings = config or Config()
    run = run_model_review(
        context,
        make,
        memory,
        incremental=settings.incremental,
        budget=settings.budget.pr_tokens,
        skipped=skipped,
    )
    for note in run.notes:
        say(note)
    return context.model_copy(update={"notes": (*context.notes, *run.notes), "model_review": run.asked}), run


# Model tokens one pull request may use across its runs in the GitHub App when `[budget] pr_tokens` is not
# set: the installation's key pays for every repository, so no pull request gets an open cheque. About
# a hundred small reviews, or one or two of the largest; a repository raises it in `.bylaw.toml`.
APP_PR_TOKENS = 500_000


def with_app_budget(config: Config) -> Config:
    if config.budget.pr_tokens is not None:
        return config
    # A ceiling only ever lowers the default: a high one must not raise what a pull request may spend.
    ceiling = config.ceiling.pr_tokens if config.ceiling else None
    cap = APP_PR_TOKENS if ceiling is None else min(APP_PR_TOKENS, ceiling)
    return config.model_copy(update={"budget": Budget(pr_tokens=cap)})


def model_gate(pull: PullRequest, config: Config) -> str | None:
    """Why the installation's key may not review this pull request, None when it may (ADR 0017).

    As in ADR 0006, code from outside the repository's trusted people does not spend the key unless a
    maintainer says so: by default only a branch of this repository by an owner, member or collaborator.
    """
    label = config.app.model_review_label
    if config.app.model_review == "all" or (label and label in {each.name for each in pull.labels}):
        return None
    if not pull.from_fork and pull.author_association in TRUSTED_ASSOCIATIONS:
        return None
    why = (
        "comes from a fork"
        if pull.from_fork
        else "is by an author who is not an owner, member or collaborator"
    )
    if config.ceiling is not None and config.ceiling.model_review == "trusted":
        # The organisation's ceiling keeps "all" out of reach, so only the label is worth naming.
        unlock = (
            f"A maintainer can add the `{label}` label to review it with the model."
            if label
            else "To review such pull requests with the model, set `[app] model_review_label` for a label."
        )
        unlock += " The organisation's `[ceiling]` keeps the review from opening to every pull request."
    else:
        unlock = (
            f"A maintainer can add the `{label}` label to review it with the model, or set"
            if label
            else "To review such pull requests with the model, set `[app] model_review_label` for a label, or"
        )
        unlock += ' `[app] model_review = "all"` in .bylaw.toml.'
    return (
        f"{MODEL_NOT_RUN}: this pull request {why}, and the GitHub App reviews those with "
        f"bylaw's own checks only. {unlock}"
    )


def check(context: ReviewContext, result: ReviewResult, say: Say) -> Validated:
    merged = result.model_copy(update={"findings": (*context.findings, *result.findings)})
    checked = validate(context, merged)
    for reason in checked.dropped:
        say(f"dropped {reason}")
    return checked
