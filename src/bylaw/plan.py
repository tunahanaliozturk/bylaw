"""Decides what to publish: which findings get inline comments and which existing threads change.

Pure functions over data, so every rule about re-runs is unit tested without GitHub.
"""

import hashlib
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

from bylaw.model import Finding, ReviewContext, Severity

FINGERPRINT = re.compile(r"<!-- bylaw:fp=([0-9a-f]{16}) -->")
_IGNORE = re.compile(r"^\s*bylaw:\s*ignore\b", re.IGNORECASE | re.MULTILINE)
_RANK = {severity: rank for rank, severity in enumerate(Severity)}


@dataclass(frozen=True, slots=True)
class Group:
    finding: Finding
    fingerprint: str
    others: tuple[Finding, ...]


@dataclass(frozen=True, slots=True)
class ThreadComment:
    body: str
    trusted: bool


@dataclass(frozen=True, slots=True)
class Thread:
    id: str
    resolved: bool
    comments: tuple[ThreadComment, ...]


@dataclass(frozen=True, slots=True)
class State:
    auto_resolved: frozenset[str]


@dataclass(frozen=True, slots=True)
class Plan:
    inline: tuple[Group, ...]
    summary_only: tuple[Group, ...]
    muted: tuple[Group, ...]
    reviewer_resolved: tuple[Group, ...]
    open_threads: tuple[Group, ...]
    resolve: tuple[str, ...]
    unresolve: tuple[str, ...]
    state: State


def added_text(context: ReviewContext) -> dict[str, dict[int, str]]:
    return {f.path: {a.number: a.text for a in f.added_lines} for f in context.files}


def fingerprint(added: Mapping[str, Mapping[int, str]], finding: Finding) -> str:
    """Hash of what the finding is about, not where it is, so moving code does not repost it."""
    lines = added.get(finding.file, {})
    snippet = " ".join(
        " ".join(lines.get(number, "").split()) for number in range(finding.line_start, finding.line_end + 1)
    )
    raw = "\0".join((finding.file, finding.category, finding.evidence or "", snippet))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def group_findings(findings: Iterable[Finding], added: Mapping[str, Mapping[int, str]]) -> tuple[Group, ...]:
    grouped: dict[tuple[str, str, str], list[Finding]] = {}
    for finding in findings:
        grouped.setdefault((finding.category, finding.evidence or "", finding.message), []).append(finding)
    return tuple(
        Group(finding=members[0], fingerprint=fingerprint(added, members[0]), others=tuple(members[1:]))
        for members in grouped.values()
    )


def make_plan(
    groups: Sequence[Group],
    threads: Sequence[Thread],
    state: State,
    threshold: Severity,
    cap: int,
) -> Plan:
    ours: dict[str, Thread] = {}
    for thread in threads:
        # ADR 0008: a fingerprint counts only in a comment bylaw or a maintainer could have written.
        if (
            thread.comments
            and thread.comments[0].trusted
            and (match := FINGERPRINT.search(thread.comments[0].body))
        ):
            ours.setdefault(match[1], thread)

    current = {group.fingerprint for group in groups}
    fixed = [(fp, thread) for fp, thread in ours.items() if fp not in current and not thread.resolved]
    auto_resolved = set(state.auto_resolved) | {fp for fp, _ in fixed}

    inline: list[Group] = []
    summary_only: list[Group] = []
    muted: list[Group] = []
    reviewer_resolved: list[Group] = []
    open_threads: list[Group] = []
    unresolve: list[str] = []
    for group in sorted(groups, key=_order):
        existing = ours.get(group.fingerprint)
        if existing is None:
            if _RANK[group.finding.severity] > _RANK[threshold] or len(inline) >= cap:
                summary_only.append(group)
            else:
                inline.append(group)
        elif any(reply.trusted and _IGNORE.search(reply.body) for reply in existing.comments[1:]):
            muted.append(group)
        elif existing.resolved and group.fingerprint in auto_resolved:
            unresolve.append(existing.id)
            auto_resolved.discard(group.fingerprint)
            open_threads.append(group)
        elif existing.resolved:
            reviewer_resolved.append(group)
        else:
            open_threads.append(group)

    return Plan(
        inline=tuple(inline),
        summary_only=tuple(summary_only),
        muted=tuple(muted),
        reviewer_resolved=tuple(reviewer_resolved),
        open_threads=tuple(open_threads),
        resolve=tuple(thread.id for _, thread in fixed),
        unresolve=tuple(unresolve),
        state=State(auto_resolved=frozenset(auto_resolved & ours.keys())),
    )


def _order(group: Group) -> tuple[int, str, int]:
    return _RANK[group.finding.severity], group.finding.file, group.finding.line_start
