"""Accepted ADRs from the base branch: the decisions a change is held to (ADR 0016)."""

import re
from collections.abc import Sequence
from dataclasses import dataclass
from itertools import takewhile
from pathlib import PurePosixPath
from typing import Protocol

from bylaw.model import Decision, text_lines

_ATX = re.compile(r"^ {0,3}(?P<hashes>#{1,6})\s+(?P<title>.+?)\s*#*\s*$")
_SETEXT = re.compile(r"^ {0,3}(?:=+|-+)\s*$")
_FENCE = re.compile(r"^ {0,3}(?P<fence>`{3,}|~{3,})")
_LIST_ITEM = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s")
_NUMBER = re.compile(r"^\d+[.)]?\s*")
# `Status: Accepted`, `* Status: accepted` (MADR 2), `status: accepted` (MADR front matter), `## Status: x`.
_STATUS_LINE = re.compile(r"^\s*(?:#{1,6}\s+|[-*+]\s+)?status\s*:\s*(?P<value>\S.*)$", re.IGNORECASE)
_FRONT_TITLE = re.compile(r"^title\s*:\s*(?P<title>\S.*?)\s*$", re.IGNORECASE)
_STATUS_ROW = re.compile(r"^\s*\|\s*status\s*\|\s*(?P<value>[^|]*?)\s*\|", re.IGNORECASE)
_DECISION_NAMES = frozenset({"decision", "decision outcome"})
# A status is read clause by clause, each by its first word, and the last clause that says something wins:
# "Accepted, superseded by 0012" is superseded, a history ending in "2023-02-01 accepted" is accepted, and
# "Supersedes [3. Keep the deprecated logger](...)" or "the old way is now obsolete" says nothing.
_IN_FORCE = frozenset({"accepted", "approved", "implemented", "adopted", "decided"})
_RETIRED = frozenset(
    {"superseded", "deprecated", "rejected", "replaced", "obsolete", "withdrawn", "declined", "not"}
)
_PENDING = frozenset({"proposed", "draft", "pending", "wip", "rfc", "review"})
_LINK = re.compile(r"!?\[[^\]]*\]\([^)]*\)")
_CLAUSE = re.compile(r"[.;,]|\s/\s|\s-\s")
# Bullets, a repeated "Status:", a leading date and "under" or "in" (review) come before the word.
_LEAD = re.compile(
    r"^[\s\-*+:|]*(?:status\s*:\s*)?(?:\d{4}-\d{2}-\d{2}\b[\s:,\-]*)?(?:under\s+|in\s+)?", re.IGNORECASE
)
_WILDCARD = re.compile(r"[*?\[]")
_NOT_ADRS = re.compile(r"^(?:readme|index)\.md$|template", re.IGNORECASE)
_ADR_DIRECTORIES = frozenset({"adr", "adrs", "decisions", "decision-records", "architecture-decisions"})
_DOC_DIRECTORIES = frozenset({"docs", "doc", "documentation"})

# Each ADR is one GitHub call; the newest are read first.
MAX_ADR_FILES = 40
# The decisions' share of the brief, in characters: about 650 tokens each and 4,000 in all.
DECISION_CHARS = 2_000
DECISIONS_CHARS = 12_000
_LISTED = 10
# The status line the brief shows, which may be a long history entry.
_STATUS_CHARS = 120


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
        if (preamble or heading) and (
            match := _STATUS_LINE.match(_unbold(line)) or (preamble and _STATUS_ROW.match(_unbold(line)))
        ):
            return match["value"].strip()
        if heading and heading[0] > 1:
            preamble = False
    return None


def effective(status: str) -> tuple[str, str] | None:
    """The status line that decides, and whether it is `in force`, `retired` or `pending`; None when no
    clause names a status bylaw knows."""
    found: tuple[str, str] | None = None
    for line in status.split("\n"):
        for clause in _CLAUSE.split(_LINK.sub("", line)):
            words = _LEAD.sub("", clause).lower().split()
            word = words[0] if words else ""
            for kind, known in (("in force", _IN_FORCE), ("retired", _RETIRED), ("pending", _PENDING)):
                if word in known:
                    found = (kind, line.strip().lstrip("-*+ ").strip())
    return found


def accepted(status: str) -> bool:
    """In force: the last clause that names a status says accepted or the like (ADR 0016)."""
    return (found := effective(status)) is not None and found[0] == "in force"


class DecisionSource(Protocol):
    def list_base_tree(self, directory: str) -> frozenset[str]: ...

    def read_base_many(self, paths: Sequence[str]) -> dict[str, str | None]: ...


def is_adr(path: str, globs: Sequence[str]) -> bool:
    """A Markdown file the ADR globs match, other than an index, a README or a template."""
    name = PurePosixPath(path).name
    return (
        path.endswith(".md")
        and _NOT_ADRS.search(name) is None
        and any(PurePosixPath(path).full_match(glob) for glob in globs)
    )


def scope(path: str) -> str:
    """The directory an ADR binds: the one above its `adr` or `decisions` directory and any `docs` around
    it, so `packages/api/docs/adr/0002-x.md` binds `packages/api`, and `docs/adr/0001-x.md` everything."""
    parts = PurePosixPath(path).parts[:-1]
    marks = [i for i, part in enumerate(parts) if part.lower() in _ADR_DIRECTORIES]
    if not marks:
        return ""
    above = list(parts[: marks[0]])
    if above and above[-1].lower() in _DOC_DIRECTORIES:
        above.pop()
    return "/".join(above)


def collect_decisions(
    source: DecisionSource, globs: Sequence[str], changed: Sequence[str] = ()
) -> tuple[tuple[Decision, ...], tuple[str, ...]]:
    """`changed` are the paths the change touches: a package's ADRs are read only when it has one."""
    paths = [path for path in _adr_paths(source, globs) if _binds(scope(path), changed)]
    notes: list[str] = []
    if len(paths) > MAX_ADR_FILES:
        notes.append(
            f"Only the newest {MAX_ADR_FILES} of {len(paths)} ADR files were read for decisions; "
            f"{', '.join(paths[MAX_ADR_FILES:][:_LISTED])} and any older ones were not."
        )
        paths = paths[:MAX_ADR_FILES]
    texts = source.read_base_many(paths)
    decisions: list[Decision] = []
    unreadable: list[str] = []
    used = 0
    for index, path in enumerate(paths):
        if (text := texts.get(path)) is None or (decision := _decision(path, text)) is None:
            continue
        if isinstance(decision, str):
            unreadable.append(f"{path} ({decision})")
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
    if unreadable:
        # Retired and proposed ADRs are left out on purpose; these may be decisions bylaw failed to see.
        notes.append(f"These ADRs were left out because bylaw could not read them: {', '.join(unreadable)}.")
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


def _decision(path: str, markdown: str) -> Decision | str | None:
    """The decision, None for an ADR that is not in force, or why bylaw could not read it."""
    status = status_of(markdown)
    if status is None:
        return "no status"
    found = effective(status)
    if found is None:
        first = text_lines(status)[0][:_STATUS_CHARS]
        return f'status "{first}" not recognised'
    if found[0] != "in force":
        return None
    document = _parse(markdown)
    start = next(
        (i for i in sorted(document.headings) if _name(document.headings[i][1]) in _DECISION_NAMES), None
    )
    if start is None:
        return "no Decision section"
    body = [document.lines[i] for i in document.section(start)]
    while body and not body[-1].strip():
        body.pop()
    title = _title(document) or PurePosixPath(path).stem
    return Decision(
        path=path,
        title=title,
        status=found[1][:_STATUS_CHARS],
        start=start + 1,
        text="\n".join(body),
        directory=scope(path),
    )


def _binds(directory: str, changed: Sequence[str]) -> bool:
    return not directory or any(path.startswith(f"{directory}/") for path in changed)


def _adr_paths(source: DecisionSource, globs: Sequence[str]) -> list[str]:
    """ADR files on the base branch, newest (highest number) first."""
    found: set[str] = set()
    for glob in globs:
        # The directories before the first wildcard; `**/adr/**` lists the whole tree, one call on GitHub.
        directory = "/".join(
            takewhile(lambda part: not _WILDCARD.search(part), PurePosixPath(glob).parts[:-1])
        )
        found.update(path for path in source.list_base_tree(directory) if is_adr(path, globs))
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
