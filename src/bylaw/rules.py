"""Collects the repository's written rules from the base branch (ADR 0004), per directory (ADR 0013)."""

from collections.abc import Sequence
from pathlib import PurePosixPath
from typing import Protocol

from bylaw import linters
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
    # In Ruff's order of precedence within one directory.
    ".py": (".ruff.toml", "ruff.toml", "pyproject.toml"),
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


def _groups(suffix: str) -> list[tuple[str, ...]]:
    """Rule file names that compete, in precedence order: Ruff reads one configuration, the first it finds."""
    names = LINTER_FILES.get(suffix, ())
    return [names] if suffix == ".py" else [(name,) for name in names]


class BaseReader(Protocol):
    def read_base(self, path: str) -> str | None: ...

    def list_base(self, directory: str) -> frozenset[str]: ...


_DOTNET_SUFFIXES = (".cs", ".vb")


def governs(config_path: str, file: str) -> bool:
    """Whether a linter configuration speaks for a file's language; ruff.toml says nothing on a .ts file."""
    name, suffix = PurePosixPath(config_path).name, PurePosixPath(file).suffix
    if name == ".editorconfig":
        return suffix in _DOTNET_SUFFIXES
    return name in LINTER_FILES.get(suffix, ())


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
    for group in dict.fromkeys(group for suffix in suffixes for group in _groups(suffix)):
        for path in group:
            if (text := _usable(path, base.read_base(path))) is not None:
                sources.append(RuleSource(path=path, kind=RuleKind.LINTER, text=text))
                break
    for path in PROSE_FILES:
        text = base.read_base(path)
        if text is not None:
            sources.append(RuleSource(path=path, kind=RuleKind.PROSE, text=text))
    nested, notes = _nested(live, base)
    # .github/CONTRIBUTING.md and docs/CONTRIBUTING.md are root rules for the whole repository; a change
    # under .github/ must not turn them into rules of that directory.
    root_paths = {rule.path for rule in sources}
    nested = [rule for rule in nested if rule.path not in root_paths]
    read: list[RuleSource] = []
    problems: list[str] = []
    for rule in (*sources, *nested):
        if rule.kind == RuleKind.PROSE:
            read.append(rule)
            continue
        try:
            read.append(
                rule.model_copy(update={"linter": linters.parse(rule.path, rule.text, base.read_base)})
            )
        except ValueError as error:
            read.append(rule)
            problems.append(f"{rule.path}: {error}; a finding cannot cite its rule ids.")
    return tuple(read), (*notes, *problems)


def _nested(paths: Sequence[str], base: BaseReader) -> tuple[list[RuleSource], tuple[str, ...]]:
    """For each changed file and each rule file name, the nearest directory above it that has one.

    Competing Ruff files count as one name: the nearest directory with any of them, its first by precedence.
    """
    directories = sorted({d for path in paths for d in _ancestors(path)}, key=lambda d: (d.count("/"), d))
    listed = {d: base.list_base(d) for d in directories[:MAX_RULE_DIRECTORIES]}
    texts: dict[str, str | None] = {}
    found: dict[str, RuleSource] = {}
    for path in paths:
        for group in [(name,) for name in NESTED_PROSE] + _groups(PurePosixPath(path).suffix):
            if (hit := _nearest(path, group, listed, texts, base)) is not None:
                found[hit.path] = hit
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


def _nearest(
    path: str,
    group: tuple[str, ...],
    listed: dict[str, frozenset[str]],
    texts: dict[str, str | None],
    base: BaseReader,
) -> RuleSource | None:
    for directory in _ancestors(path):
        for name in group:
            rule_path = f"{directory}/{name}"
            if name not in listed.get(directory, frozenset()):
                continue
            if rule_path not in texts:
                texts[rule_path] = _usable(name, base.read_base(rule_path))
            if (text := texts[rule_path]) is not None:
                kind = RuleKind.PROSE if name in NESTED_PROSE else RuleKind.LINTER
                return RuleSource(path=rule_path, kind=kind, text=text, directory=directory)
    return None


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
