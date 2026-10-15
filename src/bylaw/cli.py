"""Command line entry point."""

import argparse
import json
import os
import sys
import tempfile
from collections.abc import Sequence
from importlib.metadata import version
from pathlib import Path

from pydantic import BaseModel

from bylaw.config import Config, ConfigError, load_config
from bylaw.context import build_context
from bylaw.engine import PROVIDERS, OutReview, ReviewError, api_key_for, make_reviewer
from bylaw.evaluation.cases import load_cases
from bylaw.evaluation.report import render
from bylaw.evaluation.run import AnswerReviewer, CaseRun, NoModel, prepare, run_all
from bylaw.evaluation.score import score
from bylaw.github import GitHubClient, GitHubError, GitHubSource
from bylaw.local_git import LocalGitSource
from bylaw.model import Finding, ReviewContext, ReviewResult, Severity
from bylaw.plan import remaining
from bylaw.prompt import render_input, system_prompt
from bylaw.publish import preview, publish
from bylaw.source import SourceError
from bylaw.validate import Validated, validate


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
    source.add_argument("--context", help="ReviewContext JSON from `bylaw context`")
    run.add_argument("--repo", help="owner/name; defaults to GITHUB_REPOSITORY")
    run.add_argument("--provider", choices=PROVIDERS, default="anthropic")
    run.add_argument("--model", help="model name; defaults to claude-opus-5-5 for anthropic")
    run.add_argument("--effort", help="reasoning effort passed to the model (anthropic default: high)")
    run.add_argument("--post", action="store_true", help="publish to the pull request (needs --pr)")
    run.add_argument(
        "--fail-on",
        choices=[*Severity, "none"],
        default="none",
        help="exit 1 when a finding at or above this severity remains",
    )
    _add_eval(commands.add_parser("eval", help="review the labelled evaluation set and score the result"))
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
    answer.add_argument("--provider", choices=PROVIDERS)
    go.add_argument("--model", help="model name; defaults to claude-opus-5-5 for anthropic")
    go.add_argument("--effort", help="reasoning effort passed to the model")
    mark.add_argument("--runs", required=True, help="directory `bylaw eval run` wrote")
    mark.add_argument("--label", required=True, help="model or host and date, for the report title")
    mark.add_argument("--input-price", type=float, help="USD per million input tokens")
    mark.add_argument("--output-price", type=float, help="USD per million output tokens")
    mark.add_argument("--output", help="write the report here instead of standard output")


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
            return _eval(args)
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
        _write(render(score(cases, saved), args.label, **prices).rstrip("\n"), args.output)
        return 0
    with tempfile.TemporaryDirectory() as work:
        if args.eval_command == "prepare":
            prepare(root, cases, Path(args.out), Path(work))
            return 0
        if args.no_model:
            run_all(root, cases, lambda _: NoModel(), Path(args.out), Path(work))
            return 0
        if args.answers:
            answers = Path(args.answers)
            run_all(
                root, cases, lambda c: AnswerReviewer(answers / f"{c.id}.json"), Path(args.out), Path(work)
            )
            return 0
        key = api_key_for(args.provider)
        if key is None:
            variable = {"anthropic": "ANTHROPIC_API_KEY", "openai": "OPENAI_API_KEY"}[args.provider]
            _say(f"eval run needs {variable}; it calls the model once per case")
            return 2
        reviewer = make_reviewer(args.provider, args.model, args.effort, key)
        runs = run_all(root, cases, lambda _: reviewer, Path(args.out), Path(work))
        _say(f"reviewed {len(runs)} case(s); {sum(r.error is not None for r in runs)} failed.")
    return 0


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
    api_url = os.environ.get("GITHUB_API_URL", "https://api.github.com")
    with GitHubClient(token, api_url, os.environ.get("GITHUB_GRAPHQL_URL")) as client:
        return build_context(GitHubSource(client, repo, args.pr))


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
        _write(preview(context, checked.result, Config()))
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
    if args.post and args.pr is None:
        raise SourceError("--post needs --pr")
    if args.pr is None:
        context = _read(ReviewContext, args.context)
        context, result = _with_model_review(context, args)
        checked = _check(context, result)
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
        source = GitHubSource(client, repo, args.pr)
        context, result = _with_model_review(build_context(source), args)
        checked = _check(context, result)
        if not args.post:
            return checked, checked.result.findings
        config = load_config(source.read_base(".bylaw.toml"))
        plan = publish(client, repo, args.pr, context=context, result=checked.result, config=config)
        _say(f"posted {len(plan.inline)} comment(s), resolved {len(plan.resolve)}.")
    return checked, remaining(plan)


def _with_model_review(
    context: ReviewContext, args: argparse.Namespace
) -> tuple[ReviewContext, ReviewResult]:
    """The context with notes about the model run, and the model's result (empty when it did not run)."""
    key = api_key_for(args.provider)
    notes: list[str] = []
    result = ReviewResult()
    if key is None:
        notes.append("The model review did not run: no API key is set.")
    else:
        text, left_out = render_input(context)
        if left_out:
            notes.append(f"Left out of the model review for size: {', '.join(left_out)}.")
        try:
            result = make_reviewer(args.provider, args.model, args.effort, key).review(system_prompt(), text)
        except ReviewError as error:
            notes.append(f"The model review did not run: {error}.")
    for note in notes:
        _say(note)
    return context.model_copy(update={"notes": (*context.notes, *notes)}), result


def _check(context: ReviewContext, result: ReviewResult) -> Validated:
    merged = result.model_copy(update={"findings": (*context.findings, *result.findings)})
    checked = validate(context, merged)
    for reason in checked.dropped:
        _say(f"dropped {reason}")
    return checked


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
