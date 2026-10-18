"""Accepted ADRs from the base branch: the decisions a change is held to (ADR 0016)."""

import re
from collections.abc import Sequence
from dataclasses import dataclass
from itertools import takewhile
from pathlib import PurePosixPath

from bylaw.model import Decision, text_lines
from bylaw.rules import BaseReader

_ATX = re.compile(r"^ {0,3}(?P<hashes>#{1,6})\s+(?P<title>.+?)\s*#*\s*$")
_SETEXT = re.compile(r"^ {0,3}(?:=+|-+)\s*$")
_FENCE = re.compile(r"^ {0,3}(?P<fence>`{3,}|~{3,})")
_LIST_ITEM = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s")
_NUMBER = re.compile(r"^\d+[.)]?\s*")
# `Status: Accepted`, `* Status: accepted` (MADR 2), `status: accepted` (MADR front matter), `## Status: x`.
_STATUS_LINE = re.compile(r"^\s*(?:#{1,6}\s+|[-*+]\s+)?status\s*:\s*(?P<value>\S.*)$", re.IGNORECASE)
_FRONT_TITLE = re.compile(r"^title\s*:\s*(?P<title>\S.*?)\s*$", re.IGNORECASE)
_DECISION_NAMES = frozenset({"decision", "decision outcome"})
_ACCEPTED = re.compile(r"\b(?:accepted|approved)\b", re.IGNORECASE)
# "Supersedes 0003" keeps an ADR in force; "superseded by 0012" does not.
_RETIRED = re.compile(r"\b(?:superseded|deprecated|rejected|replaced|obsolete|withdrawn)\b", re.IGNORECASE)
_WILDCARD = re.compile(r"[*?\[]")

# Each ADR is one GitHub call; the newest are read first.
MAX_ADR_FILES = 40
# The decisions' share of the brief, in characters: about 650 tokens each and 4,000 in all.
DECISION_CHARS = 2_000
DECISIONS_CHARS = 12_000
_LISTED = 10


@dataclass(frozen=True, slots=True)
class _Document:
    """An ADR's lines as GitHub numbers them, with its headings outside code fences and front matter."""

    lines: list[str]
    # Line index to (level, title), ATX and setext alike.
    headings: dict[int, tuple[int, str]]
    # Lines inside code fences, fence lines included: never headings, never a status.
    fenced: frozenset[int]
    # The index after a leading `---` front matter block, 0 without one.
    front_end: int

    def section(self, start: int) -> list[int]:
        """The line indexes of the section a heading opens, up to the next heading of its level or higher."""
        level = self.headings[start][0]
        end = next(
            (i for i in sorted(self.headings) if i > start and self.headings[i][0] <= level), len(self.lines)
        )
        return list(range(start, end))


def _parse(markdown: str) -> _Document:
    lines = text_lines(markdown)
    front_end = 0
    if lines and lines[0].strip() == "---":
        close = next((i for i in range(1, len(lines)) if lines[i].strip() in {"---", "..."}), None)
        front_end = 0 if close is None else close + 1
    headings: dict[int, tuple[int, str]] = {}
    fenced: set[int] = set()
    fence: str | None = None
    for index in range(front_end, len(lines)):
        line = lines[index]
        if fence is not None:
            fenced.add(index)
            if line.lstrip().startswith(fence):
                fence = None
            continue
        if opened := _FENCE.match(line):
            fence = opened["fence"]
            fenced.add(index)
        elif atx := _ATX.match(line):
            headings[index] = (len(atx["hashes"]), atx["title"])
        elif (
            index + 1 < len(lines)
            and line.strip()
            and not _LIST_ITEM.match(line)
            and index - 1 not in headings
            and _SETEXT.match(lines[index + 1])
        ):
            headings[index] = (1 if "=" in lines[index + 1] else 2, line.strip())
    return _Document(lines, headings, frozenset(fenced), front_end)


def _name(title: str) -> str:
    """A heading's name for matching: `## **3. Decision:**` is `decision`."""
    return _NUMBER.sub("", _unbold(title).strip()).strip().rstrip(":").strip().lower()


def status_of(markdown: str) -> str | None:
    """The status as written, from a `Status:` line or front matter key above the first section, or from a
    Status section (Nygard, adr-tools). A `Status:` further down is prose about something else."""
    document = _parse(markdown)
    preamble = True
    for index, line in enumerate(document.lines):
        if index in document.fenced:
            continue
        heading = document.headings.get(index)
        if heading and _name(heading[1]) == "status":
            return _section_status(document, index)
        if (preamble or heading) and (match := _STATUS_LINE.match(_unbold(line))):
            return match["value"].strip()
        if heading and heading[0] > 1:
            preamble = False
    return None


def accepted(status: str) -> bool:
    """In force: accepted, and not also retired, as in "Accepted, superseded by 0012" (ADR 0016)."""
    return _ACCEPTED.search(status) is not None and _RETIRED.search(status) is None


def is_adr(path: str, globs: Sequence[str]) -> bool:
    return path.endswith(".md") and any(PurePosixPath(path).full_match(glob) for glob in globs)


def collect_decisions(
    source: BaseReader, globs: Sequence[str]
) -> tuple[tuple[Decision, ...], tuple[str, ...]]:
    paths = _adr_paths(source, globs)
    notes: list[str] = []
    if len(paths) > MAX_ADR_FILES:
        notes.append(
            f"Only the newest {MAX_ADR_FILES} of {len(paths)} ADR files were read for decisions; "
            f"{', '.join(paths[MAX_ADR_FILES:][:_LISTED])} and any older ones were not."
        )
        paths = paths[:MAX_ADR_FILES]
    decisions: list[Decision] = []
    used = 0
    for index, path in enumerate(paths):
        if (text := source.read_base(path)) is None or (decision := _decision(path, text)) is None:
            continue
        decision = _cut(decision)
        if used + len(decision.text) > DECISIONS_CHARS:
            # Newest first until the budget is full: an older decision is the likelier one to be stale.
            older = paths[index:]
            more = f", and {len(older) - _LISTED} more" if len(older) > _LISTED else ""
            notes.append(
                "The decisions are capped to keep the brief small; these older ADR files were left out: "
                f"{', '.join(older[:_LISTED])}{more}."
            )
            break
        if decision.cut:
            notes.append(f"{path}: only the start of its decision is shown, to keep the brief small.")
        used += len(decision.text)
        decisions.append(decision)
    return tuple(decisions), tuple(notes)


def _cut(decision: Decision) -> Decision:
    if len(decision.text) <= DECISION_CHARS:
        return decision
    kept: list[str] = []
    size = 0
    for line in text_lines(decision.text):
        if size + len(line) + 1 > DECISION_CHARS:
            # A paragraph is often one long line: show its start rather than nothing.
            if room := DECISION_CHARS - size:
                kept.append(line[:room])
            break
        kept.append(line)
        size += len(line) + 1
    return decision.model_copy(update={"text": "\n".join(kept), "cut": True})


def _decision(path: str, markdown: str) -> Decision | None:
    status = status_of(markdown)
    if status is None or not accepted(status):
        return None
    document = _parse(markdown)
    start = next(
        (i for i in sorted(document.headings) if _name(document.headings[i][1]) in _DECISION_NAMES), None
    )
    if start is None:
        return None
    body = [document.lines[i] for i in document.section(start)]
    while body and not body[-1].strip():
        body.pop()
    title = _title(document) or PurePosixPath(path).stem
    return Decision(
        path=path, title=title, status=status.splitlines()[0], start=start + 1, text="\n".join(body)
    )


def _adr_paths(source: BaseReader, globs: Sequence[str]) -> list[str]:
    """ADR files on the base branch, newest (highest number) first."""
    # ponytail: only the files directly in each glob's fixed directory are listed, not its subdirectories,
    # which keeps it to one listing per glob; list the base tree recursively if teams nest their ADRs.
    found: set[str] = set()
    for glob in globs:
        directory = "/".join(
            takewhile(lambda part: not _WILDCARD.search(part), PurePosixPath(glob).parts[:-1])
        )
        prefix = f"{directory}/" if directory else ""
        found.update(path for name in source.list_base(directory) if is_adr(path := prefix + name, globs))
    return sorted(found, key=_number, reverse=True)


def _number(path: str) -> tuple[int, str]:
    name = PurePosixPath(path).name
    match = re.search(r"\d+", name)
    return (int(match[0]) if match else -1, name)


def _section_status(document: _Document, start: int) -> str | None:
    values: list[str] = []
    for index in document.section(start)[1:]:
        line = document.lines[index]
        if index in document.fenced or index in document.headings or _SETEXT.match(line):
            continue
        if value := _unbold(line).strip().lstrip("-*+ ").strip():
            values.append(value)
    return "\n".join(values) or None


def _title(document: _Document) -> str | None:
    """The first level one heading after any front matter, else the front matter's `title:`, else the first
    heading. MADR's template starts its front matter with a YAML comment that is not a title."""
    headings = [document.headings[i][1] for i in sorted(document.headings) if document.headings[i][0] == 1]
    if headings:
        return headings[0]
    for line in document.lines[1 : max(document.front_end - 1, 1)]:
        if match := _FRONT_TITLE.match(line):
            return match["title"].strip("'\"")
    first = min(document.headings, default=None)
    return None if first is None else document.headings[first][1]


def _unbold(line: str) -> str:
    return line.replace("**", "").replace("__", "")
