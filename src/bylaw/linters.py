"""Reads which rule ids a repository's linters enable, from their configuration files (ADR 0013).

Nothing here runs a linter or any repository code: TOML, JSON, YAML and .editorconfig are parsed as data, and
configuration written as code (eslint.config.js, .eslintrc.js) stays prose. What a file says that cannot be
read as ids, such as an `extends`, is kept as a note for the brief.
"""

import json
import posixpath
import re
import tomllib
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from functools import lru_cache
from io import StringIO
from pathlib import PurePosixPath

from ruamel.yaml import YAML
from ruamel.yaml.error import YAMLError

from bylaw.editorconfig import glob_matches, glob_regex, read_sections
from bylaw.model import FileRules, LinterRules

TOOLS = frozenset({"ruff", "eslint", "golangci-lint", "dotnet"})

_RUFF_DEFAULT = ("E4", "E7", "E9", "F")
_PYLINT = frozenset({"PLC", "PLE", "PLR", "PLW"})
_LETTERS = re.compile(r"[A-Z]*")
_GOLANGCI_V1_DEFAULT = ("errcheck", "gosimple", "govet", "ineffassign", "staticcheck", "unused")
_GOLANGCI_STANDARD = ("errcheck", "govet", "ineffassign", "staticcheck", "unused")
# Strings first, so a "//" inside a URL is kept; then line and block comments.
_JSON_COMMENT = re.compile(r'("(?:\\.|[^"\\])*")|//[^\n]*|/\*.*?\*/', re.DOTALL)
_DOTNET_KEY = re.compile(r"dotnet_diagnostic\.([a-z0-9_]+)\.severity")
_DOTNET_CATEGORY = re.compile(r"dotnet_analyzer_diagnostic\.(category-[a-z0-9_]+)\.severity")
_DOTNET_ON = frozenset({"error", "warning", "suggestion"})
_DOTNET_OFF = frozenset({"none", "silent"})
_ANALYSIS = re.compile(r"<(AnalysisLevel\w*|AnalysisMode\w*)>\s*([^<]+?)\s*</\1>")


type Read = Callable[[str], str | None]

# How many `extend` links of a Ruff configuration are followed on the base branch.
RUFF_EXTEND_DEPTH = 5


def parse(path: str, text: str, read: Read | None = None) -> LinterRules | None:
    """The ids a configuration file enables; None when it holds none bylaw can read.

    `read` reads another base-branch file, for a Ruff `extend`. Raises ValueError, with a reason fit for the
    review notes, when the file is not valid in its format.
    """
    name = PurePosixPath(path).name
    if name in {"ruff.toml", ".ruff.toml"}:
        return _ruff(path, _toml(text), read)
    if name == "pyproject.toml":
        tool = _table(_toml(text).get("tool"))
        return _ruff(path, _table(tool["ruff"]), read) if "ruff" in tool else None
    reader = _READERS.get(name)
    return reader(text) if reader is not None else None


def normalise(tool: str, rule_id: str) -> str:
    if tool in {"ruff", "dotnet"}:
        return rule_id.upper()
    return rule_id.lower() if tool == "golangci-lint" else rule_id


def enables(rules: LinterRules, rule_id: str, path: str) -> bool | None:
    """Whether the id is on for a path relative to the configuration's directory; None if it is silent."""
    if rules.tool == "ruff":
        if any(_ruff_best(f.ignore, rule_id) >= 0 for f in rules.per_file if _ruff_pattern(f.pattern, path)):
            return False
        on, off = _ruff_best(rules.select, rule_id), _ruff_best(rules.ignore, rule_id)
        if on > off:
            return True
        # Off when the configuration says so, or when bylaw read all of it; otherwise it may be on.
        return False if off >= 0 or rules.complete else None
    # .NET sections are .editorconfig globs; ESLint overrides are globs where `**/` may be no directory.
    matches = glob_matches if rules.tool == "dotnet" else _linter_glob
    decision = _exact(rules.select, rules.ignore, rule_id)
    for override in rules.per_file:
        said = _exact(override.select, override.ignore, rule_id)
        if said is not None and matches(override.pattern, path):
            decision = said
    return decision


def _ruff_pattern(pattern: str, path: str) -> bool:
    # A leading "!" makes a Ruff per-file pattern apply to every file it does not match.
    if pattern.startswith("!"):
        return not _linter_glob(pattern[1:], path)
    return _linter_glob(pattern, path)


def _linter_glob(pattern: str, path: str) -> bool:
    return _linter_regex(pattern).fullmatch(path) is not None


@lru_cache(maxsize=256)
def _linter_regex(pattern: str) -> re.Pattern[str]:
    """A glob as Ruff and ESLint read it: `**/` is zero or more directories, no slash matches any depth."""
    pattern = pattern.removeprefix("./").removeprefix("/")
    regex = "(?:.*/)?".join(glob_regex(piece) for piece in pattern.split("**/"))
    if "/" not in pattern:
        regex = f"(?:.*/)?{regex}"
    try:
        return re.compile(regex)
    except re.error:
        return re.compile(r"(?!)")  # a pattern no tool could use matches nothing


def describe(rules: LinterRules) -> str:
    lines = [f"Rule ids a finding may cite as evidence, written {rules.tool}:<id>:"]
    prefix = " (a prefix enables every id that starts with it)" if rules.tool == "ruff" else ""
    if rules.select:
        lines.append(f"- enabled: {', '.join(rules.select)}{prefix}")
    if rules.ignore:
        lines.append(f"- disabled: {', '.join(rules.ignore)}")
    for override in rules.per_file:
        parts = [f"enabled {', '.join(override.select)}"] if override.select else []
        parts += [f"disabled {', '.join(override.ignore)}"] if override.ignore else []
        lines.append(f"- for {override.pattern}: {'; '.join(parts)}")
    lines.extend(f"- {note}" for note in rules.notes)
    if not rules.complete:
        lines.append(
            "- bylaw did not read all that this configuration turns on, so an id not listed may still be on"
        )
    return "\n".join(lines)


def _exact(select: tuple[str, ...], ignore: tuple[str, ...], rule_id: str) -> bool | None:
    if rule_id in ignore:
        return False
    return True if rule_id in select or "*" in select else None


def _ruff_best(selectors: tuple[str, ...], code: str) -> int:
    """The specificity of the most specific selector that matches the code, -1 when none does."""
    best = -1
    for selector in selectors:
        if selector == "ALL":
            best = max(best, 0)
            continue
        letters, code_letters = _LETTERS.match(selector), _LETTERS.match(code)
        same_linter = (
            letters is not None
            and code_letters is not None
            and (letters[0] == code_letters[0] or (letters[0] == "PL" and code_letters[0] in _PYLINT))
        )
        # "E" is pycodestyle and must not reach eradicate's ERA001; "PL" is every pylint group.
        if same_linter and code.startswith(selector):
            best = max(best, len(selector))
    return best


@dataclass(frozen=True, slots=True)
class _RuffLayer:
    """What one Ruff configuration file says, before its `extend` is applied."""

    select: tuple[str, ...] | None
    extend_select: tuple[str, ...]
    ignore: tuple[str, ...]
    per_file: tuple[FileRules, ...] | None
    extend_per_file: tuple[FileRules, ...]
    extend: str | None


def _ruff_layer(table: Mapping[str, object]) -> _RuffLayer:
    lint = _table(table.get("lint"))

    def has(key: str) -> bool:
        return key in lint or key in table

    def value(key: str) -> object:
        # The `lint` table replaced the top-level keys; Ruff still reads both, and so does bylaw.
        return lint.get(key, table.get(key))

    def codes(key: str) -> tuple[str, ...]:
        return tuple(code.upper() for code in _strings(value(key)))

    def files(key: str) -> tuple[FileRules, ...]:
        return tuple(
            FileRules(pattern=pattern, ignore=tuple(code.upper() for code in _strings(selected)))
            for pattern, selected in _table(value(key)).items()
        )

    extend = table.get("extend")
    return _RuffLayer(
        select=codes("select") if has("select") else None,
        extend_select=codes("extend-select"),
        ignore=(*codes("ignore"), *codes("extend-ignore")),
        per_file=files("per-file-ignores") if has("per-file-ignores") else None,
        extend_per_file=files("extend-per-file-ignores"),
        extend=extend if isinstance(extend, str) else None,
    )


def _ruff(path: str, table: Mapping[str, object], read: Read | None) -> LinterRules:
    chain = [(path, _ruff_layer(table))]  # nearest first
    notes: list[str] = []
    complete = True
    while (extend := chain[-1][1].extend) is not None:
        target = _inside(chain[-1][0], extend)
        data = _extended(target, {link for link, _ in chain}, len(chain), read)
        if target is None or data is None:
            notes.append(f"extends {extend}, which bylaw could not read")
            complete = False
            break
        chain.append((target, _ruff_layer(data)))
        notes.append(f"extends {target}, read from the base branch")
    # Ruff applies the farthest file first; a `select` starts over, `extend-select` and `ignore` add.
    select: tuple[str, ...] = _RUFF_DEFAULT if complete else ()
    ignore: tuple[str, ...] = ()
    per_file: tuple[FileRules, ...] = ()
    home = _dirname(path)
    for link, layer in reversed(chain):
        if layer.select is not None:
            select, ignore = layer.select, ()
        select = (*select, *layer.extend_select)
        ignore = (*ignore, *layer.ignore)
        if layer.per_file is not None:
            per_file = _rebase(layer.per_file, _dirname(link), home)
        per_file = (*per_file, *_rebase(layer.extend_per_file, _dirname(link), home))
    return LinterRules(
        tool="ruff",
        select=tuple(dict.fromkeys(select)),
        ignore=tuple(dict.fromkeys(ignore)),
        per_file=per_file,
        notes=tuple(notes),
        complete=complete,
    )


def _extended(target: str | None, seen: set[str], depth: int, read: Read | None) -> dict[str, object] | None:
    """The Ruff settings of an extended file, or None when it cannot or must not be read."""
    if target is None or target in seen or depth > RUFF_EXTEND_DEPTH or read is None:
        return None
    text = read(target)
    if text is None:
        return None
    try:
        data = _toml(text)
    except ValueError:
        return None
    if PurePosixPath(target).name == "pyproject.toml":
        return _table(_table(data.get("tool")).get("ruff"))
    return data


def _inside(config: str, extend: str) -> str | None:
    """The repository path an `extend` names, or None when it leaves the repository."""
    if extend.startswith(("/", "~")) or ":" in extend or "\\" in extend:
        return None
    joined = posixpath.normpath(posixpath.join(_dirname(config), extend))
    return None if joined in {".", ".."} or joined.startswith("../") else joined


def _rebase(rules: tuple[FileRules, ...], origin: str, home: str) -> tuple[FileRules, ...]:
    """Patterns of a file in `origin`, made relative to `home`; ones that cannot reach `home` are dropped."""
    if origin == home:
        return rules
    under = origin == "" or home.startswith(f"{origin}/")
    prefix = (home[len(origin) + 1 :] if origin else home) + "/"
    kept: list[FileRules] = []
    for rule in rules:
        pattern = rule.pattern
        if "/" not in pattern or pattern.startswith("**/"):
            kept.append(rule)
        elif under and pattern.startswith(prefix):
            kept.append(rule.model_copy(update={"pattern": pattern.removeprefix(prefix)}))
    return tuple(kept)


def _dirname(path: str) -> str:
    return posixpath.dirname(path)


def _eslint(data: object) -> LinterRules:
    config = _table(data)
    select, ignore = _eslint_rules(config.get("rules"))
    per_file: list[FileRules] = []
    for override in _list(config.get("overrides")):
        entry = _table(override)
        on, off = _eslint_rules(entry.get("rules"))
        files = entry.get("files")
        for pattern in [files] if isinstance(files, str) else _strings(files):
            per_file.append(FileRules(pattern=pattern, select=on, ignore=off))
    extends = config.get("extends")
    names = [extends] if isinstance(extends, str) else _strings(extends)
    notes = (f"extends {', '.join(names)}, whose rules are not listed",) if names else ()
    inherited = bool(names) or any("extends" in _table(o) for o in _list(config.get("overrides")))
    return LinterRules(
        tool="eslint",
        select=select,
        ignore=ignore,
        per_file=tuple(per_file),
        notes=notes,
        complete=not inherited,
    )


def _eslint_rules(rules: object) -> tuple[tuple[str, ...], tuple[str, ...]]:
    on: list[str] = []
    off: list[str] = []
    for rule, setting in _table(rules).items():
        level = setting[0] if isinstance(setting, list) and setting else setting
        if isinstance(level, str):
            level = level.lower()  # ESLint reads "Error" and "WARN" as well
        if level in ("error", "warn", 1, 2):
            on.append(rule)
        elif level in ("off", 0):  # 0 == False, so a YAML `false` counts too
            off.append(rule)
    return tuple(on), tuple(off)


def _eslint_json(text: str) -> LinterRules:
    # ESLint allows comments in .eslintrc.json; they are removed, strings are left alone.
    stripped = _JSON_COMMENT.sub(lambda match: match[1] or "", text)
    try:
        return _eslint(json.loads(stripped))
    except json.JSONDecodeError as error:
        raise ValueError(f"not valid JSON ({error.msg} at line {error.lineno})") from error


def _golangci(text: str) -> LinterRules:
    config = _table(_yaml(text))
    linters = _table(config.get("linters"))
    enable = [name.lower() for name in _strings(linters.get("enable"))]
    disable = tuple(name.lower() for name in _strings(linters.get("disable")))
    notes: list[str] = []
    # Tuples, not sets: a YAML value may be a list, which a set lookup cannot hash.
    if config.get("version") in ("2", 2):
        default = linters.get("default")
        base = {"all": ("*",), "none": (), "fast": ()}.get(
            default if isinstance(default, str) else "", _GOLANGCI_STANDARD
        )
        if default == "fast":
            notes.append("default set fast, whose linters are not listed")
    elif linters.get("enable-all") is True:
        base = ("*",)
    else:
        base = () if linters.get("disable-all") is True else _GOLANGCI_V1_DEFAULT
    if presets := _strings(linters.get("presets")):
        notes.append(f"presets {', '.join(presets)}, whose linters are not listed")
    select = tuple(dict.fromkeys(name for name in (*base, *enable) if name not in disable))
    return LinterRules(
        tool="golangci-lint", select=select, ignore=disable, notes=tuple(notes), complete=not notes
    )


def _dotnet(properties: list[tuple[str, str, int]]) -> tuple[tuple[str, ...], tuple[str, ...]]:
    on: list[str] = []
    off: list[str] = []
    for key, value, _ in properties:
        if (match := _DOTNET_KEY.fullmatch(key)) is None:
            continue
        severity = value.lower()
        if severity in _DOTNET_ON:
            on.append(match[1].upper())
        elif severity in _DOTNET_OFF:
            off.append(match[1].upper())
    return tuple(on), tuple(off)


def _analyzer_settings(properties: list[tuple[str, str, int]]) -> list[str]:
    """Severities set for every analyzer or a whole category, which name no ids."""
    settings: list[str] = []
    for key, value, _ in properties:
        if key == "dotnet_analyzer_diagnostic.severity":
            settings.append(f"all analyzers {value.lower()}")
        elif match := _DOTNET_CATEGORY.fullmatch(key):
            settings.append(f"{match[1]} {value.lower()}")
    return settings


def _editorconfig(text: str) -> LinterRules | None:
    _, sections = read_sections(text)
    per_file = tuple(
        FileRules(pattern=glob, select=on, ignore=off)
        for glob, properties in sections
        for on, off in [_dotnet(properties)]
        if on or off
    )
    notes = tuple(
        f"for {glob}: {', '.join(settings)}; ids these turn on are not listed"
        for glob, properties in sections
        if (settings := _analyzer_settings(properties))
    )
    if not per_file and not notes:
        return None
    return LinterRules(tool="dotnet", per_file=per_file, notes=notes, complete=not notes)


def _globalconfig(text: str) -> LinterRules | None:
    preamble, _ = read_sections(text)
    on, off = _dotnet(preamble)
    settings = _analyzer_settings(preamble)
    notes = (f"{', '.join(settings)}; ids these turn on are not listed",) if settings else ()
    if not (on or off or notes):
        return None
    return LinterRules(tool="dotnet", select=on, ignore=off, notes=notes, complete=not notes)


def _build_props(text: str) -> LinterRules | None:
    # A regular expression rather than an XML parser: the file is untrusted and only these values matter.
    settings = [f"{name} {value}" for name, value in _ANALYSIS.findall(text)]
    if not settings:
        return None
    note = f"{', '.join(settings)}: ids these turn on are not listed"
    return LinterRules(tool="dotnet", notes=(note,), complete=False)


def _toml(text: str) -> dict[str, object]:
    try:
        return tomllib.loads(text)
    except tomllib.TOMLDecodeError as error:
        raise ValueError(f"not valid TOML ({error})") from error


def _yaml(text: str) -> object:
    # The safe loader builds only plain data: a tag that would construct a Python object is an error.
    try:
        return YAML(typ="safe", pure=True).load(StringIO(text))
    except YAMLError as error:
        raise ValueError(f"not valid YAML ({type(error).__name__})") from error


def _table(value: object) -> dict[str, object]:
    return {k: v for k, v in value.items() if isinstance(k, str)} if isinstance(value, Mapping) else {}


def _list(value: object) -> list[object]:
    return list(value) if isinstance(value, list | tuple) else []


def _strings(value: object) -> list[str]:
    # Only plain strings: str() of a nested YAML alias would expand it into text of any size.
    return [item for item in _list(value) if isinstance(item, str)]


_READERS: dict[str, Callable[[str], LinterRules | None]] = {
    ".eslintrc.json": _eslint_json,
    ".eslintrc.yml": lambda text: _eslint(_yaml(text)),
    ".eslintrc.yaml": lambda text: _eslint(_yaml(text)),
    ".golangci.yml": _golangci,
    ".golangci.yaml": _golangci,
    ".editorconfig": _editorconfig,
    ".globalconfig": _globalconfig,
    "Directory.Build.props": _build_props,
}
