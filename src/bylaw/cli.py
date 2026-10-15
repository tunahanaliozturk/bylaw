"""Command line entry point."""

import argparse
import json
import os
import sys
from collections.abc import Sequence
from importlib.metadata import version
from pathlib import Path

from bylaw.config import Config, ConfigError, load_config
from bylaw.context import build_context
from bylaw.github import GitHubClient, GitHubError, GitHubSource
from bylaw.local_git import LocalGitSource
from bylaw.model import ReviewContext, ReviewResult
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

    show = commands.add_parser("prompt", help="print what a reviewer model would read, for host agents")
    show.add_argument("--context", required=True, help="ReviewContext JSON from `bylaw context`")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "context":
            _write(_context(args).model_dump_json(indent=2))
        elif args.command == "validate":
            checked = _validated(args)
            payload = {"result": checked.result.model_dump(mode="json"), "dropped": list(checked.dropped)}
            _write(json.dumps(payload, indent=2, ensure_ascii=False))
        elif args.command == "prompt":
            context = ReviewContext.model_validate_json(Path(args.context).read_text(encoding="utf-8"))
            text, _ = render_input(context)
            _write(f"{system_prompt()}\n---\n{text}")
        else:
            _post(args)
    except (SourceError, GitHubError, ConfigError, OSError, ValueError) as error:
        print(f"bylaw: {error}", file=sys.stderr)
        return 2
    return 0


def _write(text: str) -> None:
    # Bytes, not text: a Windows console defaults to cp1252 and cannot print every character in a diff.
    sys.stdout.buffer.write(text.encode("utf-8") + b"\n")
    sys.stdout.flush()


def _context(args: argparse.Namespace) -> ReviewContext:
    if args.pr is None:
        return build_context(LocalGitSource(Path(args.path), args.base, args.repo))
    repo, token = _repo_and_token(args.repo)
    api_url = os.environ.get("GITHUB_API_URL", "https://api.github.com")
    with GitHubClient(token, api_url, os.environ.get("GITHUB_GRAPHQL_URL")) as client:
        return build_context(GitHubSource(client, repo, args.pr))


def _validated(args: argparse.Namespace) -> Validated:
    context = ReviewContext.model_validate_json(Path(args.context).read_text(encoding="utf-8"))
    result = (
        ReviewResult.model_validate_json(Path(args.result).read_text(encoding="utf-8"))
        if args.result
        else ReviewResult()
    )
    # The deterministic findings travel in the context; merged here so a run without a model posts them.
    merged = result.model_copy(update={"findings": (*context.findings, *result.findings)})
    return validate(context, merged)


def _post(args: argparse.Namespace) -> None:
    context = ReviewContext.model_validate_json(Path(args.context).read_text(encoding="utf-8"))
    checked = _validated(args)
    for reason in checked.dropped:
        print(f"bylaw: dropped {reason}", file=sys.stderr)
    if args.dry_run:
        _write(preview(context, checked.result, Config()))
        return
    repo, token = _repo_and_token(args.repo)
    api_url = os.environ.get("GITHUB_API_URL", "https://api.github.com")
    with GitHubClient(token, api_url, os.environ.get("GITHUB_GRAPHQL_URL")) as client:
        # Read again rather than trusting the context file: the config must come from the base branch.
        config = load_config(GitHubSource(client, repo, args.pr).read_base(".bylaw.toml"))
        plan = publish(client, repo, args.pr, context=context, result=checked.result, config=config)
    print(
        f"bylaw: posted {len(plan.inline)} comment(s), resolved {len(plan.resolve)}, "
        f"reopened {len(plan.unresolve)} thread(s), updated the summary.",
        file=sys.stderr,
    )


def _repo_and_token(repo_arg: str | None) -> tuple[str, str]:
    repo = repo_arg or os.environ.get("GITHUB_REPOSITORY")
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if not token:
        raise SourceError("GITHUB_TOKEN or GH_TOKEN is required with --pr")
    if not repo:
        raise SourceError("--repo or GITHUB_REPOSITORY is required with --pr")
    return repo, token
