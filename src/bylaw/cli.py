"""Command line entry point."""

import argparse
import json
import os
import sys
import tempfile
from collections.abc import Callable, Sequence
from importlib.metadata import version
from pathlib import Path

from pydantic import BaseModel

from bylaw.config import Config, ConfigError, load_config
from bylaw.context import build_context
from bylaw.engine import (
    PROVIDERS,
    OutReview,
    Reviewer,
    ReviewError,
    api_key_for,
    can_review,
    key_variable,
    make_reviewer,
)
from bylaw.evaluation.cases import Case, load_cases
from bylaw.evaluation.report import report
from bylaw.evaluation.run import AnswerReviewer, CaseRun, NoModel, prepare, run_all
from bylaw.evaluation.snapshot import snapshot_pull_request
from bylaw.github import GitHubClient, GitHubError, GitHubSource
from bylaw.gitlab import GitLabClient, GitLabMergeRequest
from bylaw.local_git import LocalGitSource
from bylaw.model import Finding, ReviewContext, ReviewResult, Severity
from bylaw.prompt import render_input, system_prompt
from bylaw.publish import preview, publish
from bylaw.pull_review import check, review_change, review_pull_request, with_model_review
from bylaw.source import SourceError
from bylaw.validate import Validated, validate

_MODEL_HELP = (
    "model name, or the deployment name on azure-openai; defaults to claude-opus-5-5 for the Claude "
    "providers (anthropic.claude-opus-5-5 on bedrock) and is required for the others"
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="bylaw",
        description="Review pull requests against your repository's own rules and requirements.",
    )
    parser.add_argument("--version", action="version", version=f"bylaw {version('bylaw')}")
    commands = parser.add_subparsers(dest="command", required=True)

    context = commands.add_parser("context", help="print the review context as JSON")
    target = context.add_mutually_exclusive_group(required=True)
    target.add_argument("--pr", type=int, help="pull request number, read through the GitHub API")
    target.add_argument("--base", help="review committed changes from this ref to HEAD in a local repository")
    context.add_argument("--repo", help="owner/name; defaults to GITHUB_REPOSITORY in --pr mode")
    context.add_argument("--path", default=".", help="local repository directory for --base (default: .)")
    context.add_argument("--output", help="write the JSON to this file (UTF-8) instead of standard output")

    check = commands.add_parser("validate", help="drop findings the context cannot back up")
    check.add_argument("--context", required=True, help="ReviewContext JSON from `bylaw context`")
    check.add_argument("--result", help="ReviewResult JSON from a reviewer (default: no extra findings)")

    post = commands.add_parser("post", help="publish a review to a pull request")
    post.add_argument("--context", required=True, help="ReviewContext JSON from `bylaw context`")
    post.add_argument("--result", help="ReviewResult JSON from a reviewer (default: no extra findings)")
    where = post.add_mutually_exclusive_group(required=True)
    where.add_argument("--pr", type=int, help="pull request number")
    where.add_argument("--dry-run", action="store_true", help="print what would be posted instead")
    post.add_argument("--repo", help="owner/name; defaults to GITHUB_REPOSITORY")

    commands.add_parser("schema", help="print the JSON schema a reviewer's result must follow")

    show = commands.add_parser("prompt", help="print what a reviewer model would read, for host agents")
    show.add_argument("--context", required=True, help="ReviewContext JSON from `bylaw context`")
    show.add_argument("--output", help="write the brief to this file (UTF-8) instead of standard output")

    run = commands.add_parser("review", help="review a change end to end: context, model, checks, comments")
    source = run.add_mutually_exclusive_group(required=True)
    source.add_argument("--pr", type=int, help="pull request number")
    source.add_argument(
        "--gitlab-mr", type=int, metavar="IID", help="GitLab merge request IID (needs GITLAB_TOKEN)"
    )
    source.add_argument("--context", help="ReviewContext JSON from `bylaw context`")
    run.add_argument("--repo", help="owner/name; defaults to GITHUB_REPOSITORY")
    run.add_argument(
        "--project",
        help="GitLab project id or path; defaults to CI_MERGE_REQUEST_PROJECT_ID, then CI_PROJECT_ID",
    )
    run.add_argument("--provider", choices=PROVIDERS, default="anthropic", help="see docs/providers.md")
    run.add_argument("--model", help=_MODEL_HELP)
    run.add_argument("--effort", help="reasoning effort passed to the model (anthropic default: high)")
    run.add_argument("--base-url", help="server URL for openai-compatible, such as http://localhost:11434/v1")
    run.add_argument(
        "--post",
        action="store_true",
        help="publish to the pull request or merge request (needs --pr or --gitlab-mr)",
    )
    run.add_argument(
        "--fail-on",
        choices=[*Severity, "none"],
        default="none",
        help="exit 1 when a finding at or above this severity remains",
    )
    _add_eval(commands.add_parser("eval", help="review the labelled evaluation set and score the result"))
    serve = commands.add_parser("mcp", help="serve the review tools to any MCP client over standard I/O")
    serve.add_argument(
        "--root",
        action="append",
        help="a directory whose repositories local reviews may read; repeat for more (default: the "
        "working directory)",
    )
    serve.add_argument(
        "--allow-post", action="store_true", help="also offer the post tool, which publishes to pull requests"
    )
    return parser


def _add_eval(evaluation: argparse.ArgumentParser) -> None:
    steps = evaluation.add_subparsers(dest="eval_command", required=True)
    ready = steps.add_parser("prepare", help="write each case's context and brief for a host model")
    go = steps.add_parser("run", help="review every case and save the results")
    mark = steps.add_parser("score", help="score saved results against the labels")
    for step in (ready, go, mark):
        step.add_argument("--set", default="eval", help="evaluation set directory (default: eval)")
        step.add_argument("--only", default="", help="only cases whose id starts with this")
    ready.add_argument("--out", required=True, help="directory for <id>.context.json and <id>.brief.txt")
    go.add_argument("--out", required=True, help="directory for one result file per case; reruns resume")
    answer = go.add_mutually_exclusive_group(required=True)
    answer.add_argument("--answers", help="directory of <id>.json results a host model wrote")
    answer.add_argument("--no-model", action="store_true", help="bylaw's own checks only, no reviewer")
    answer.add_argument("--provider", choices=PROVIDERS, help="see docs/providers.md")
    go.add_argument("--model", help=_MODEL_HELP)
    go.add_argument("--effort", help="reasoning effort passed to the model")
    go.add_argument("--base-url", help="server URL for openai-compatible, such as http://localhost:11434/v1")
    go.add_argument("--max-cost", type=float, help="stop starting new cases once this many USD are spent")
    go.add_argument("--input-price", type=float, help="USD per million input tokens, for --max-cost")
    go.add_argument("--output-price", type=float, help="USD per million output tokens, for --max-cost")
    mark.add_argument("--runs", required=True, help="directory `bylaw eval run` wrote")
    mark.add_argument("--label", required=True, help="model or host and date, for the report title")
    mark.add_argument("--input-price", type=float, help="USD per million input tokens")
    mark.add_argument("--output-price", type=float, help="USD per million output tokens")
    mark.add_argument("--output", help="write the report here instead of standard output")
    freeze = steps.add_parser("snapshot", help="freeze a public pull request into a real case (reads GitHub)")
    freeze.add_argument("--repo", required=True, help="owner/name of a permissively licensed project")
    freeze.add_argument("--pr", type=int, required=True, help="pull request number")
    freeze.add_argument(
        "--comment", type=int, help="review comment id; the case is the commit it was made on"
    )
    freeze.add_argument("--id", required=True, help="case id, the directory under <set>/cases/")
    freeze.add_argument("--set", default="eval/real", help="real set directory (default: eval/real)")


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "context":
            _write(_context(args).model_dump_json(indent=2), args.output)
        elif args.command == "validate":
            checked = _validated(args)
            payload = {"result": checked.result.model_dump(mode="json"), "dropped": list(checked.dropped)}
            _write(json.dumps(payload, indent=2, ensure_ascii=False))
        elif args.command == "review":
            return _review(args)
        elif args.command == "schema":
            _write(json.dumps(OutReview.model_json_schema(), indent=2))
        elif args.command == "prompt":
            text, left_out = render_input(_read(ReviewContext, args.context))
            if left_out:
                _say(f"Left out of the review for size: {', '.join(left_out)}.")
            _write(f"{system_prompt()}\n---\n{text}", args.output)
        elif args.command == "eval":
            return _snapshot(args) if args.eval_command == "snapshot" else _eval(args)
        elif args.command == "mcp":
            return _mcp(args)
        else:
            _post(args)
    except (SourceError, GitHubError, ConfigError, OSError, ValueError, ReviewError) as error:
        _say(str(error))
        return 2
    return 0


def _eval(args: argparse.Namespace) -> int:
    root = Path(args.set)
    cases = tuple(c for c in load_cases(root) if c.id.startswith(args.only))
    if args.eval_command == "score":
        saved = [
            CaseRun.model_validate_json(p.read_text(encoding="utf-8")) for p in Path(args.runs).glob("*.json")
        ]
        prices = {"input_price": args.input_price, "output_price": args.output_price}
        _write(report(cases, saved, args.label, **prices).rstrip("\n"), args.output)
        return 0
    with tempfile.TemporaryDirectory() as work:
        if args.eval_command == "prepare":
            prepare(root, cases, Path(args.out), Path(work))
            return 0
        limit: Callable[[Sequence[CaseRun]], bool] | None = None
        if args.max_cost is not None:
            if args.input_price is None or args.output_price is None:
                _say("--max-cost needs --input-price and --output-price")
                return 2
            limit = _spend_limit(args.max_cost, args.input_price, args.output_price)
        make: Callable[[Case], Reviewer]
        if args.no_model:
            make, identity = (lambda _: NoModel()), "no-model"
        elif args.answers:
            answers = Path(args.answers)
            make, identity = (
                (lambda c: AnswerReviewer(answers / f"{c.id}.json")),
                f"answers:{answers.resolve().name}",
            )
        else:
            if not can_review(args.provider):
                variable = key_variable(args.provider)
                _say(f"eval run needs {variable} or BYLAW_API_KEY; it calls the model once per case")
                return 2
            key = api_key_for(args.provider)
            reviewer = make_reviewer(args.provider, args.model, args.effort, key, args.base_url)
            make = lambda _: reviewer  # noqa: E731 - one reviewer for every case
            identity = f"{args.provider}:{args.model or 'default model'}:{args.effort or 'default effort'}"
            if args.base_url:
                # Two servers can serve different weights under one model name.
                identity += f"@{args.base_url}"
        _say(f"reviewing {len(cases)} case(s) with {identity}; finished cases in {args.out} are reused")
        runs = run_all(root, cases, make, Path(args.out), identity, stop=limit)
        failed = sum(r.error is not None for r in runs)
        _say(f"reviewed {len(runs)} case(s); {failed} failed.")
        if len(runs) < len(cases):
            _say(f"stopped at the {args.max_cost} USD limit; {len(cases) - len(runs)} case(s) not started.")
        return 1 if failed else 0
    return 0


def _snapshot(args: argparse.Namespace) -> int:
    root = Path(args.set)
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if not token:
        # The token is read, never stored: it only lifts the rate limit on public reads.
        _say('eval snapshot needs GITHUB_TOKEN or GH_TOKEN, for example GH_TOKEN="$(gh auth token)"')
        return 2
    api_url = os.environ.get("GITHUB_API_URL", "https://api.github.com")
    with GitHubClient(token, api_url, os.environ.get("GITHUB_GRAPHQL_URL")) as client:
        pull = snapshot_pull_request(client, args.repo, args.pr, args.comment, root / "cases" / args.id)
    _say(f"froze {pull.url} at {pull.head_sha[:12]} into {root / 'cases' / args.id}; label it in case.toml")
    return 0


def _mcp(args: argparse.Namespace) -> int:
    try:
        from bylaw.mcp_server import make_server  # noqa: PLC0415 - the mcp extra is optional
    except ModuleNotFoundError as error:
        if (error.name or "").partition(".")[0] not in {"mcp", "mcp_types"}:
            raise
        _say('bylaw mcp needs the mcp extra: uvx --from "bylaw[mcp]" bylaw mcp')
        return 2
    # Claude Code sets CLAUDE_PROJECT_DIR in the server's own environment, not where ${...} in args expand.
    default = os.environ.get("CLAUDE_PROJECT_DIR")
    roots = [Path(root) for root in args.root] if args.root else [Path(default) if default else Path.cwd()]
    make_server(roots, allow_post=args.allow_post).run("stdio")
    return 0


def _spend_limit(
    max_cost: float, input_price: float, output_price: float
) -> Callable[[Sequence[CaseRun]], bool]:
    def reached(runs: Sequence[CaseRun]) -> bool:
        tokens_in = sum(r.input_tokens or 0 for r in runs)
        tokens_out = sum(r.output_tokens or 0 for r in runs)
        return (tokens_in * input_price + tokens_out * output_price) / 1_000_000 >= max_cost

    return reached


def _write(text: str, output: str | None = None) -> None:
    data = text.encode("utf-8") + b"\n"
    if output:
        # bylaw writes the file itself: a shell redirect on Windows re-encodes it as UTF-16 or adds a BOM.
        Path(output).write_bytes(data)
        return
    # Bytes, not text: a Windows console defaults to cp1252 and cannot print every character in a diff.
    sys.stdout.buffer.write(data)
    sys.stdout.flush()


def _read[M: BaseModel](model: type[M], path: str) -> M:
    raw = Path(path).read_bytes()
    # A file saved through a Windows shell redirect starts with a BOM; detect_encoding reads and strips it.
    return model.model_validate_json(raw.decode(json.detect_encoding(raw)))


def _context(args: argparse.Namespace) -> ReviewContext:
    if args.pr is None:
        return build_context(LocalGitSource(Path(args.path), args.base, args.repo))
    repo, token = _repo_and_token(args.repo)
    # A host agent names --repo, and a pull request can steer it to one whose .bylaw.toml names an
    # attacker's tracker; only the Action's own repository may say where tracker tokens go (ADR 0019).
    own = repo.lower() == os.environ.get("GITHUB_REPOSITORY", "").lower()
    api_url = os.environ.get("GITHUB_API_URL", "https://api.github.com")
    with GitHubClient(token, api_url, os.environ.get("GITHUB_GRAPHQL_URL")) as client:
        return build_context(GitHubSource(client, repo, args.pr), operator_sites=not own)


def _validated(args: argparse.Namespace) -> Validated:
    context = _read(ReviewContext, args.context)
    result = _read(ReviewResult, args.result) if args.result else ReviewResult()
    # The deterministic findings travel in the context; merged here so a run without a model posts them.
    merged = result.model_copy(update={"findings": (*context.findings, *result.findings)})
    return validate(context, merged)


def _post(args: argparse.Namespace) -> None:
    context = _read(ReviewContext, args.context)
    checked = _validated(args)
    for reason in checked.dropped:
        _say(f"dropped {reason}")
    if args.dry_run:
        settings = Config(severity_threshold=context.severity_threshold, max_comments=context.max_comments)
        _write(preview(context, checked.result, settings))
        return
    repo, token = _repo_and_token(args.repo)
    api_url = os.environ.get("GITHUB_API_URL", "https://api.github.com")
    with GitHubClient(token, api_url, os.environ.get("GITHUB_GRAPHQL_URL")) as client:
        # Read again rather than trusting the context file: the config must come from the base branch.
        config = load_config(GitHubSource(client, repo, args.pr).read_base(".bylaw.toml"))
        plan = publish(client, repo, args.pr, context=context, result=checked.result, config=config)
    _say(
        f"posted {len(plan.inline)} comment(s), resolved {len(plan.resolve)}, "
        f"reopened {len(plan.unresolve)} thread(s), updated the summary."
    )


def _repo_and_token(repo_arg: str | None) -> tuple[str, str]:
    repo = repo_arg or os.environ.get("GITHUB_REPOSITORY")
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if not token:
        raise SourceError("GITHUB_TOKEN or GH_TOKEN is required with --pr")
    if not repo:
        raise SourceError("--repo or GITHUB_REPOSITORY is required with --pr")
    return repo, token


_RANK = {severity: rank for rank, severity in enumerate(Severity)}
_NO_SECRETS_ACTORS = frozenset({"dependabot[bot]"})


def _say(text: str) -> None:
    """One line on stderr. Line breaks are flattened: in GitHub Actions a line that starts with `::` is a
    workflow command, and text from a model or a pull request must not be able to start one."""
    flat = " ".join(text.splitlines())
    print(f"bylaw: {flat}", file=sys.stderr)


def _review(args: argparse.Namespace) -> int:
    if _without_secrets():
        print(
            "::notice title=bylaw::This pull_request run has no secrets and a read-only token (a fork or "
            "Dependabot), so bylaw skipped it. Use the pull_request_target recipe for these (docs/recipes)."
        )
        return 0
    if args.post and args.pr is None and args.gitlab_mr is None:
        raise SourceError("--post needs --pr or --gitlab-mr")
    if args.gitlab_mr is not None:
        if _gitlab_fork_without_token():
            _say(
                "This merge request pipeline runs in a fork, without the project's GITLAB_TOKEN, so bylaw "
                "skipped it. See docs/hosts.md for reviewing merge requests from forks."
            )
            return 0
        checked, counted = _review_merge_request(args)
    elif args.pr is None:
        context = _read(ReviewContext, args.context)
        context, run = with_model_review(context, _reviewer(args), _say)
        checked = check(context, run.result, _say)
        counted = checked.result.findings
    else:
        checked, counted = _review_pull_request(args)
    if not args.post:
        payload = {"result": checked.result.model_dump(mode="json"), "dropped": list(checked.dropped)}
        _write(json.dumps(payload, indent=2, ensure_ascii=False))
    return _exit_code(counted, args.fail_on)


def _review_pull_request(args: argparse.Namespace) -> tuple[Validated, tuple[Finding, ...]]:
    """Review a pull request; also return the findings `--fail-on` counts (muted ones excluded)."""
    repo, token = _repo_and_token(args.repo)
    api_url = os.environ.get("GITHUB_API_URL", "https://api.github.com")
    with GitHubClient(token, api_url, os.environ.get("GITHUB_GRAPHQL_URL")) as client:
        review = review_pull_request(client, repo, args.pr, make=_reviewer(args), post=args.post, say=_say)
    return review.checked, review.counted


def _review_merge_request(args: argparse.Namespace) -> tuple[Validated, tuple[Finding, ...]]:
    """Review a GitLab merge request (ADR 0020); the same flow as a pull request."""
    project = args.project or os.environ.get("CI_MERGE_REQUEST_PROJECT_ID") or os.environ.get("CI_PROJECT_ID")
    token = os.environ.get("GITLAB_TOKEN")
    if not project:
        raise SourceError("--project or CI_MERGE_REQUEST_PROJECT_ID is required with --gitlab-mr")
    if not token:
        # CI_JOB_TOKEN cannot read a merge request's diff or post a note (docs/recipes/gitlab-ci.yml).
        raise SourceError(
            "GITLAB_TOKEN, a project access token with the Developer role, is required with --gitlab-mr"
        )
    api_url = os.environ.get("CI_API_V4_URL", "https://gitlab.com/api/v4")
    with GitLabClient(token, api_url) as client:
        merge_request = GitLabMergeRequest(client, project, args.gitlab_mr)
        config = load_config(merge_request.read_base(".bylaw.toml"))
        review = review_change(
            merge_request,
            merge_request,
            merge_request.repo,
            args.gitlab_mr,
            config,
            make=_reviewer(args),
            post=args.post,
            say=_say,
        )
    return review.checked, review.counted


def _gitlab_fork_without_token() -> bool:
    """A merge request pipeline from a fork runs in the fork, without the target project's variables."""
    source = os.environ.get("CI_MERGE_REQUEST_SOURCE_PROJECT_ID")
    fork = source is not None and source != os.environ.get("CI_MERGE_REQUEST_PROJECT_ID")
    return fork and not os.environ.get("GITLAB_TOKEN")


def _reviewer(args: argparse.Namespace) -> Callable[[], Reviewer] | None:
    key = api_key_for(args.provider)
    if not can_review(args.provider):
        return None
    return lambda: make_reviewer(args.provider, args.model, args.effort, key, args.base_url)


def _exit_code(findings: Sequence[Finding], fail_on: str) -> int:
    if fail_on == "none":
        return 0
    threshold = _RANK[Severity(fail_on)]
    failing = [f for f in findings if _RANK[f.severity] <= threshold]
    if failing:
        _say(f"{len(failing)} finding(s) at or above {fail_on}.")
        return 1
    return 0


def _without_secrets() -> bool:
    """A pull_request run that gets no secrets and a read-only token: a fork, a deleted fork or Dependabot."""
    if os.environ.get("GITHUB_EVENT_NAME") != "pull_request" or not os.environ.get("GITHUB_EVENT_PATH"):
        return False
    if os.environ.get("GITHUB_ACTOR") in _NO_SECRETS_ACTORS:
        return True
    try:
        event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text(encoding="utf-8"))
        pull = event["pull_request"]
        head_repo = pull["head"]["repo"]
        if head_repo is None:
            return True
        return bool(head_repo["full_name"] != pull["base"]["repo"]["full_name"])
    except (OSError, ValueError, KeyError, TypeError):
        return False
