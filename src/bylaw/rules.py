"""Collects the repository's written rules from the base branch (ADR 0004)."""

from collections.abc import Callable, Sequence
from pathlib import PurePosixPath

from bylaw.model import ChangedFile, RuleKind, RuleSource

PROSE_FILES = (
    "CONTRIBUTING.md",
    ".github/CONTRIBUTING.md",
    "docs/CONTRIBUTING.md",
    "AGENTS.md",
    "CLAUDE.md",
    ".github/copilot-instructions.md",
    "STYLEGUIDE.md",
)

_JAVASCRIPT = (
    "eslint.config.js",
    "eslint.config.mjs",
    "eslint.config.cjs",
    "eslint.config.ts",
    ".eslintrc.json",
    ".eslintrc.js",
    ".eslintrc.cjs",
    ".eslintrc.yml",
    ".eslintrc.yaml",
    ".prettierrc",
    ".prettierrc.json",
)

# ponytail: only configuration at the repository root is read. Nested configs (a monorepo package with its
# own ruff.toml) are a later addition.
LINTER_FILES: dict[str, tuple[str, ...]] = {
    ".py": ("ruff.toml", ".ruff.toml", "pyproject.toml"),
    **dict.fromkeys((".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx", ".vue"), _JAVASCRIPT),
    ".go": (".golangci.yml", ".golangci.yaml"),
    ".cs": (".globalconfig", "Directory.Build.props"),
    ".rb": (".rubocop.yml",),
}

# pyproject.toml is left out: most edits to it are not rule changes, and the note would be noise.
RULE_PATHS = frozenset(
    {*PROSE_FILES, *(path for paths in LINTER_FILES.values() for path in paths), ".bylaw.toml"}
) - {"pyproject.toml"}


def collect_rules(
    changed: Sequence[ChangedFile],
    read_base: Callable[[str], str | None],
    editorconfig_files: Sequence[tuple[str, str]],
) -> tuple[RuleSource, ...]:
    sources = [
        RuleSource(path=path, kind=RuleKind.EDITORCONFIG, text=text) for path, text in editorconfig_files
    ]
    suffixes = sorted({PurePosixPath(f.path).suffix for f in changed if f.status != "removed"})
    linter_paths = dict.fromkeys(path for suffix in suffixes for path in LINTER_FILES.get(suffix, ()))
    for path in linter_paths:
        text = read_base(path)
        if text is None or (path == "pyproject.toml" and "[tool.ruff" not in text):
            continue
        sources.append(RuleSource(path=path, kind=RuleKind.LINTER, text=text))
    for path in PROSE_FILES:
        text = read_base(path)
        if text is not None:
            sources.append(RuleSource(path=path, kind=RuleKind.PROSE, text=text))
    return tuple(sources)
