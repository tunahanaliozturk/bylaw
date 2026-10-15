"""Command line entry point."""

import argparse
import os
import sys
from collections.abc import Sequence
from importlib.metadata import version
from pathlib import Path

from bylaw.config import ConfigError
from bylaw.context import build_context
from bylaw.github import GitHubClient, GitHubError, GitHubSource
from bylaw.local_git import LocalGitSource
from bylaw.model import ReviewContext
from bylaw.source import SourceError


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
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        context = _context(args)
    except (SourceError, GitHubError, ConfigError) as error:
        print(f"bylaw: {error}", file=sys.stderr)
        return 2
    # Bytes, not text: a Windows console defaults to cp1252 and cannot print every character in a diff.
    sys.stdout.buffer.write(context.model_dump_json(indent=2).encode("utf-8") + b"\n")
    sys.stdout.flush()
    return 0


def _context(args: argparse.Namespace) -> ReviewContext:
    if args.pr is None:
        return build_context(LocalGitSource(Path(args.path), args.base, args.repo))
    repo = args.repo or os.environ.get("GITHUB_REPOSITORY")
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if not token:
        raise SourceError("GITHUB_TOKEN or GH_TOKEN is required with --pr")
    if not repo:
        raise SourceError("--repo or GITHUB_REPOSITORY is required with --pr")
    api_url = os.environ.get("GITHUB_API_URL", "https://api.github.com")
    with GitHubClient(token, api_url, os.environ.get("GITHUB_GRAPHQL_URL")) as client:
        return build_context(GitHubSource(client, repo, args.pr))
