"""Command line entry point."""

import argparse
from collections.abc import Sequence
from importlib.metadata import version


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="bylaw",
        description="Review pull requests against your repository's own rules and requirements.",
    )
    parser.add_argument("--version", action="version", version=f"bylaw {version('bylaw')}")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    _parser().parse_args(argv)
    return 0
