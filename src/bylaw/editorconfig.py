"""Resolves .editorconfig properties for a path, following https://spec.editorconfig.org.

Files are read through a callback so the same code works on the base branch via the GitHub API and on a
local repository. Each property remembers the file and line that set it, which becomes the evidence on a
finding.
"""

import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Self

_KNOWN = frozenset(
    {
        "indent_style",
        "indent_size",
        "tab_width",
        "end_of_line",
        "charset",
        "trim_trailing_whitespace",
        "insert_final_newline",
        "max_line_length",
        "root",
    }
)
_RANGE = re.compile(r"([+-]?\d+)\.\.([+-]?\d+)")


@dataclass(frozen=True, slots=True)
class Property:
    value: str
    source: str
    line: int


@dataclass(frozen=True, slots=True)
class _Section:
    pattern: re.Pattern[str]
    ranges: tuple[tuple[int, int], ...]
    properties: tuple[tuple[str, str, int], ...]

    @classmethod
    def from_glob(cls, glob: str, properties: tuple[tuple[str, str, int], ...]) -> Self:
        anchored = "/" in glob
        regex, ranges = _translate(glob.removeprefix("/"))
        if not anchored:
            regex = f"(?:.*/)?{regex}"
        return cls(re.compile(regex), tuple(ranges), properties)

    def matches(self, relative_path: str) -> bool:
        match = self.pattern.fullmatch(relative_path)
        if match is None:
            return False
        return all(
            value is None or low <= int(value) <= high
            for (low, high), value in zip(self.ranges, match.groups(), strict=True)
        )


@dataclass(frozen=True, slots=True)
class _File:
    path: str
    directory: str
    text: str
    root: bool
    sections: tuple[_Section, ...]


class EditorConfigResolver:
    def __init__(self, read: Callable[[str], str | None]) -> None:
        self._read = read
        self._cache: dict[str, _File | None] = {}

    @property
    def files_read(self) -> tuple[tuple[str, str], ...]:
        return tuple((f.path, f.text) for f in self._cache.values() if f is not None)

    def properties(self, path: str) -> dict[str, Property]:
        chain: list[_File] = []
        for directory in _directories(path):
            config = self._load(directory)
            if config is None:
                continue
            chain.append(config)
            if config.root:
                break
        result: dict[str, Property] = {}
        for config in reversed(chain):
            relative = path[len(config.directory) + 1 :] if config.directory else path
            for section in config.sections:
                if section.matches(relative):
                    for key, value, line in section.properties:
                        result[key] = Property(value, config.path, line)
        return result

    def _load(self, directory: str) -> _File | None:
        if directory not in self._cache:
            path = f"{directory}/.editorconfig" if directory else ".editorconfig"
            text = self._read(path)
            self._cache[directory] = None if text is None else _parse(path, directory, text)
        return self._cache[directory]


def _directories(path: str) -> list[str]:
    return ["" if str(parent) == "." else str(parent) for parent in PurePosixPath(path).parents]


def _parse(path: str, directory: str, text: str) -> _File:
    root = False
    raw: list[tuple[str, list[tuple[str, str, int]]]] = []
    # Visual Studio saves .editorconfig with a byte order mark, which would hide the first line.
    for number, line in enumerate(text.removeprefix("﻿").splitlines(), start=1):
        stripped = line.strip()
        if not stripped or stripped[0] in "#;":
            continue
        if stripped.startswith("[") and stripped.endswith("]"):
            raw.append((stripped[1:-1], []))
            continue
        key, separator, value = stripped.partition("=")
        if not separator:
            continue
        key, value = key.strip().lower(), value.strip()
        if key in _KNOWN:
            value = value.lower()
        if raw:
            raw[-1][1].append((key, value, number))
        elif key == "root":
            root = value == "true"
    sections = tuple(_Section.from_glob(glob, tuple(properties)) for glob, properties in raw)
    return _File(path=path, directory=directory, text=text, root=root, sections=sections)


def _translate(glob: str) -> tuple[str, list[tuple[int, int]]]:  # noqa: PLR0912 - one branch per glob token
    out: list[str] = []
    ranges: list[tuple[int, int]] = []
    i = 0
    while i < len(glob):
        char = glob[i]
        i += 1
        if char == "\\" and i < len(glob):
            out.append(re.escape(glob[i]))
            i += 1
        elif char == "*":
            if glob.startswith("*", i):
                out.append(".*")
                i += 1
            else:
                out.append("[^/]*")
        elif char == "?":
            out.append("[^/]")
        elif char == "[":
            end = glob.find("]", i)
            body = glob[i:end] if end != -1 else ""
            if not body or "/" in body:
                out.append(re.escape("["))
            else:
                i = end + 1
                negated = body.startswith("!")
                body = body.removeprefix("!").replace("\\", "\\\\").replace("[", "\\[").replace("^", "\\^")
                out.append(f"[^/{body}]" if negated else f"[{body}]")
        elif char == "{":
            end = _closing_brace(glob, i - 1)
            if end == -1:
                out.append(re.escape("{"))
                continue
            inner = glob[i:end]
            i = end + 1
            alternatives = _split_alternatives(inner)
            if numbers := _RANGE.fullmatch(inner):
                ranges.append((int(numbers[1]), int(numbers[2])))
                out.append(r"([+-]?\d+)")
            elif len(alternatives) > 1:
                parts: list[str] = []
                for alternative in alternatives:
                    regex, inner_ranges = _translate(alternative)
                    parts.append(regex)
                    ranges.extend(inner_ranges)
                out.append(f"(?:{'|'.join(parts)})")
            else:
                out.append(re.escape(f"{{{inner}}}"))
        else:
            out.append(re.escape(char))
    return "".join(out), ranges


def _closing_brace(glob: str, start: int) -> int:
    depth = 0
    i = start
    while i < len(glob):
        char = glob[i]
        if char == "\\":
            i += 2
            continue
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return -1


def _split_alternatives(body: str) -> list[str]:
    parts: list[str] = []
    current: list[str] = []
    depth = 0
    i = 0
    while i < len(body):
        char = body[i]
        if char == "\\" and i + 1 < len(body):
            current.append(body[i : i + 2])
            i += 2
            continue
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
        elif char == "," and depth == 0:
            parts.append("".join(current))
            current = []
            i += 1
            continue
        current.append(char)
        i += 1
    parts.append("".join(current))
    return parts
