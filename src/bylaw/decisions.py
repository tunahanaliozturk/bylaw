"""Accepted ADRs from the base branch: the decisions a change is held to (ADR 0016)."""

import re
from collections.abc import Sequence
from itertools import takewhile
from pathlib import PurePosixPath

from bylaw.model import Decision
from bylaw.rules import BaseReader

_HEADING = re.compile(r"^(?P<hashes>#{1,6})\s+(?P<title>.+?)\s*#*\s*$")
# `Status: Accepted`, `* Status: accepted` (MADR 2), `status: accepted` (MADR front matter), `## Status: x`.
_STATUS_LINE = re.compile(r"^\s*(?:#{1,6}\s+|[-*+]\s+)?status\s*:\s*(?P<value>\S.*)$", re.IGNORECASE)
_STATUS_HEADING = re.compile(r"status", re.IGNORECASE)
_DECISION_HEADING = re.compile(r"decision(?:\s+outcome)?:?", re.IGNORECASE)
_ACCEPTED = re.compile(r"\b(?:accepted|approved)\b", re.IGNORECASE)
_WILDCARD = re.compile(r"[*?\[]")

# Each ADR is one GitHub call; the newest are read first.
MAX_ADR_FILES = 40
# The decisions' share of the brief, in characters: about 650 tokens each and 4,000 in all.
DECISION_CHARS = 2_000
DECISIONS_CHARS = 12_000
_LISTED = 10


def status_of(markdown: str) -> str | None:
    """The status as written, from a `Status:` line or front matter key above the first section, or from a
    Status section (Nygard, adr-tools). A `Status:` further down is prose about something else."""
    lines = markdown.splitlines()
    preamble = True
    for index, line in enumerate(lines):
        heading = _HEADING.match(line)
        if heading and _STATUS_HEADING.fullmatch(heading["title"]):
            return _section_status(lines[index + 1 :])
        if (preamble or heading) and (match := _STATUS_LINE.match(_unbold(line))):
            return match["value"].strip()
        if heading and len(heading["hashes"]) > 1:
            preamble = False
    return None


def accepted(status: str) -> bool:
    return _ACCEPTED.search(status) is not None


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
    for line in decision.text.splitlines():
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
    lines = markdown.splitlines()
    for index, line in enumerate(lines):
        heading = _HEADING.match(line)
        if heading is None or not _DECISION_HEADING.fullmatch(heading["title"]):
            continue
        level = len(heading["hashes"])
        end = next(
            (
                j
                for j in range(index + 1, len(lines))
                if (h := _HEADING.match(lines[j])) and len(h["hashes"]) <= level
            ),
            len(lines),
        )
        body = lines[index:end]
        while body and not body[-1].strip():
            body.pop()
        title = _title(lines) or PurePosixPath(path).stem
        return Decision(
            path=path, title=title, status=status.splitlines()[0], start=index + 1, text="\n".join(body)
        )
    return None


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


def _section_status(lines: list[str]) -> str | None:
    text = list(takewhile(lambda line: _HEADING.match(line) is None, lines))
    values = [_unbold(line).strip().lstrip("-*+ ").strip() for line in text]
    status = "\n".join(value for value in values if value)
    return status or None


def _title(lines: list[str]) -> str | None:
    headings = [match for line in lines if (match := _HEADING.match(line))]
    first = next((h for h in headings if len(h["hashes"]) == 1), headings[0] if headings else None)
    return first["title"] if first else None


def _unbold(line: str) -> str:
    return line.replace("**", "").replace("__", "")
