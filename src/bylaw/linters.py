"""Reads which rule ids a repository's linters enable, from their configuration files (ADR 0013).

Nothing here runs a linter or any repository code: TOML, JSON, YAML and .editorconfig are parsed as data, and
configuration written as code (eslint.config.js, .eslintrc.js) stays prose. What a file says that cannot be
read as ids, such as an `extends`, is kept as a note for the brief.
"""

import json
import re
import tomllib
from collections.abc import Callable, Mapping
from io import StringIO
from pathlib import PurePosixPath

from ruamel.yaml import YAML
from ruamel.yaml.error import YAMLError

from bylaw.editorconfig import glob_matches, read_sections
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
_DOTNET_ON = frozenset({"error", "warning", "suggestion"})
_DOTNET_OFF = frozenset({"none", "silent"})
_ANALYSIS = re.compile(r"<(AnalysisLevel\w*|AnalysisMode\w*)>\s*([^<]+?)\s*</\1>")


def parse(path: str, text: str) -> LinterRules | None:
    """The ids a configuration file enables; None when it holds none bylaw can read.

    Raises ValueError, with a reason fit for the review notes, when the file is not valid in its format.
    """
    name = PurePosixPath(path).name
    reader = _READERS.get(name)
    return reader(text) if reader is not None else None


def normalise(tool: str, rule_id: str) -> str:
    if tool in {"ruff", "dotnet"}:
        return rule_id.upper()
    return rule_id.lower() if tool == "golangci-lint" else rule_id


def enables(rules: LinterRules, rule_id: str, path: str) -> bool | None:
    """Whether the id is on for a path relative to the configuration's directory; None if it is silent."""
    if rules.tool == "ruff":
        # Ruff uses the nearest configuration alone, so it always decides.
        on = _ruff_best(rules.select, rule_id) > _ruff_best(rules.ignore, rule_id)
        ignored = any(
            _ruff_best(f.ignore, rule_id) >= 0 for f in rules.per_file if glob_matches(f.pattern, path)
        )
        return on and not ignored
    decision = _exact(rules.select, rules.ignore, rule_id)
    for override in rules.per_file:
        said = _exact(override.select, override.ignore, rule_id)
        if said is not None and glob_matches(override.pattern, path):
            decision = said
    return decision


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


def _ruff(table: Mapping[str, object]) -> LinterRules:
    lint = _table(table.get("lint"))

    def codes(key: str) -> tuple[str, ...]:
        # The `lint` table replaced the top-level keys; Ruff still reads both, and so does bylaw.
        return tuple(code.upper() for code in _strings(lint.get(key, table.get(key))))

    select = codes("select") if "select" in lint or "select" in table else _RUFF_DEFAULT
    select = (*select, *codes("extend-select"))
    ignore = (*codes("ignore"), *codes("extend-ignore"))
    per_file = tuple(
        FileRules(pattern=pattern, ignore=tuple(code.upper() for code in _strings(selected)))
        for key in ("per-file-ignores", "extend-per-file-ignores")
        for pattern, selected in _table(lint.get(key, table.get(key))).items()
    )
    notes = (f"extends {table['extend']}, which bylaw does not read",) if "extend" in table else ()
    return LinterRules(tool="ruff", select=select, ignore=ignore, per_file=per_file, notes=notes)


def _ruff_toml(text: str) -> LinterRules:
    return _ruff(_toml(text))


def _pyproject(text: str) -> LinterRules | None:
    tool = _table(_toml(text).get("tool"))
    return _ruff(_table(tool["ruff"])) if "ruff" in tool else None


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
    return LinterRules(tool="eslint", select=select, ignore=ignore, per_file=tuple(per_file), notes=notes)


def _eslint_rules(rules: object) -> tuple[tuple[str, ...], tuple[str, ...]]:
    on: list[str] = []
    off: list[str] = []
    for rule, setting in _table(rules).items():
        level = setting[0] if isinstance(setting, list) and setting else setting
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
    # Tuples, not sets: a YAML value may be a list, which a set lookup cannot hash.
    if config.get("version") in ("2", 2):
        default = linters.get("default")
        base = {"all": ("*",), "none": (), "fast": ()}.get(
            default if isinstance(default, str) else "", _GOLANGCI_STANDARD
        )
    elif linters.get("enable-all") is True:
        base = ("*",)
    else:
        base = () if linters.get("disable-all") is True else _GOLANGCI_V1_DEFAULT
    select = tuple(dict.fromkeys(name for name in (*base, *enable) if name not in disable))
    return LinterRules(tool="golangci-lint", select=select, ignore=disable)


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


def _editorconfig(text: str) -> LinterRules | None:
    _, sections = read_sections(text)
    per_file = tuple(
        FileRules(pattern=glob, select=on, ignore=off)
        for glob, properties in sections
        for on, off in [_dotnet(properties)]
        if on or off
    )
    return LinterRules(tool="dotnet", per_file=per_file) if per_file else None


def _globalconfig(text: str) -> LinterRules | None:
    preamble, _ = read_sections(text)
    on, off = _dotnet(preamble)
    return LinterRules(tool="dotnet", select=on, ignore=off) if on or off else None


def _build_props(text: str) -> LinterRules | None:
    # A regular expression rather than an XML parser: the file is untrusted and only these values matter.
    settings = [f"{name} {value}" for name, value in _ANALYSIS.findall(text)]
    if not settings:
        return None
    return LinterRules(tool="dotnet", notes=(f"{', '.join(settings)}: ids these turn on are not listed",))


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
    "ruff.toml": _ruff_toml,
    ".ruff.toml": _ruff_toml,
    "pyproject.toml": _pyproject,
    ".eslintrc.json": _eslint_json,
    ".eslintrc.yml": lambda text: _eslint(_yaml(text)),
    ".eslintrc.yaml": lambda text: _eslint(_yaml(text)),
    ".golangci.yml": _golangci,
    ".golangci.yaml": _golangci,
    ".editorconfig": _editorconfig,
    ".globalconfig": _globalconfig,
    "Directory.Build.props": _build_props,
}
