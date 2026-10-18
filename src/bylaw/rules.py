"""Collects the repository's written rules from the base branch (ADR 0004), per directory (ADR 0013)."""

from collections.abc import Sequence
from pathlib import PurePosixPath
from typing import Protocol

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

# The instruction files a package of a monorepo may have for itself.
NESTED_PROSE = ("AGENTS.md", "CLAUDE.md", "CONTRIBUTING.md")

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
_NESTED_RULE_NAMES = frozenset({*NESTED_PROSE, *(n for names in LINTER_FILES.values() for n in names)}) - {
    "pyproject.toml"
}

# Each directory costs one GitHub call when the base tree is too large to read at once.
MAX_RULE_DIRECTORIES = 40
_LISTED = 10


class BaseReader(Protocol):
    def read_base(self, path: str) -> str | None: ...

    def list_base(self, directory: str) -> frozenset[str]: ...


def is_rule_file(path: str) -> bool:
    name = PurePosixPath(path).name
    return path in RULE_PATHS or name == ".editorconfig" or name in _NESTED_RULE_NAMES


def collect_rules(
    changed: Sequence[ChangedFile], base: BaseReader, editorconfig_files: Sequence[tuple[str, str]]
) -> tuple[tuple[RuleSource, ...], tuple[str, ...]]:
    """The rule sources and any notes about what was not read."""
    sources = [
        RuleSource(path=path, kind=RuleKind.EDITORCONFIG, text=text, directory=_parent(path))
        for path, text in editorconfig_files
    ]
    live = [f.path for f in changed if f.status != "removed"]
    suffixes = sorted({PurePosixPath(path).suffix for path in live})
    linter_paths = dict.fromkeys(path for suffix in suffixes for path in LINTER_FILES.get(suffix, ()))
    for path in linter_paths:
        if (text := _usable(path, base.read_base(path))) is not None:
            sources.append(RuleSource(path=path, kind=RuleKind.LINTER, text=text))
    for path in PROSE_FILES:
        text = base.read_base(path)
        if text is not None:
            sources.append(RuleSource(path=path, kind=RuleKind.PROSE, text=text))
    nested, notes = _nested(live, base)
    return (*sources, *nested), notes


def _nested(paths: Sequence[str], base: BaseReader) -> tuple[list[RuleSource], tuple[str, ...]]:
    """For each changed file and each rule file name, the nearest directory above it that has one."""
    directories = sorted({d for path in paths for d in _ancestors(path)}, key=lambda d: (d.count("/"), d))
    listed = {d: base.list_base(d) for d in directories[:MAX_RULE_DIRECTORIES]}
    texts: dict[str, str | None] = {}
    found: dict[str, RuleSource] = {}
    for path in paths:
        for name in (*NESTED_PROSE, *LINTER_FILES.get(PurePosixPath(path).suffix, ())):
            for directory in _ancestors(path):
                rule_path = f"{directory}/{name}"
                if name not in listed.get(directory, frozenset()):
                    continue
                if rule_path not in texts:
                    texts[rule_path] = _usable(name, base.read_base(rule_path))
                if (text := texts[rule_path]) is not None:
                    kind = RuleKind.PROSE if name in NESTED_PROSE else RuleKind.LINTER
                    found[rule_path] = RuleSource(path=rule_path, kind=kind, text=text, directory=directory)
                    break
    rules = sorted(found.values(), key=lambda r: (r.directory.count("/"), r.directory, r.path))
    if len(directories) <= MAX_RULE_DIRECTORIES:
        return rules, ()
    skipped = directories[MAX_RULE_DIRECTORIES:]
    shown = ", ".join(skipped[:_LISTED]) + (
        f", and {len(skipped) - _LISTED} more" if len(skipped) > _LISTED else ""
    )
    note = (
        f"Rule files were looked for in {MAX_RULE_DIRECTORIES} of the {len(directories)} directories that "
        f"hold changed files, the ones nearest the root; {shown} were not read."
    )
    return rules, (note,)


def _usable(path: str, text: str | None) -> str | None:
    # A pyproject.toml without Ruff settings says nothing about rules; Ruff itself looks further up.
    if text is None or (PurePosixPath(path).name == "pyproject.toml" and "[tool.ruff" not in text):
        return None
    return text


def _ancestors(path: str) -> list[str]:
    """The directories above a path, nearest first, without the root."""
    return [str(parent) for parent in PurePosixPath(path).parents if str(parent) != "."]


def _parent(path: str) -> str:
    parent = str(PurePosixPath(path).parent)
    return "" if parent == "." else parent
