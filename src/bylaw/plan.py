"""Decides what to publish: which findings get inline comments and which existing threads change.

Pure functions over data, so every rule about re-runs is unit tested without GitHub.
"""

import hashlib
import html
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from pathlib import PurePosixPath
from typing import Literal, get_args

from bylaw.model import Category, Finding, ReviewContext, ReviewMemory, Severity, Suppression

FINGERPRINT = re.compile(r"<!-- bylaw:fp=([0-9a-f]{16}) -->")
_IGNORE = re.compile(r"^\s*bylaw:\s*ignore\b", re.IGNORECASE | re.MULTILINE)
_RANK = {severity: rank for rank, severity in enumerate(Severity)}
# What `&#8203;` in a comment reads as once unescaped.
_ZERO_WIDTH_SPACE = chr(0x200B)


@dataclass(frozen=True, slots=True)
class Group:
    finding: Finding
    fingerprint: str
    others: tuple[Finding, ...]
    # Who accepted it: the maintainer whose reply muted it, or the person who resolved its thread.
    by: str | None = None


@dataclass(frozen=True, slots=True)
class ThreadComment:
    body: str
    trusted: bool
    by_pr_author: bool = False
    author: str = ""


@dataclass(frozen=True, slots=True)
class Thread:
    id: str
    resolved: bool
    comments: tuple[ThreadComment, ...]
    # The thread's current end line on the head; None when GitHub marks it outdated.
    line: int | None = None
    # The end line it was posted on, for pairing outdated threads.
    original_line: int | None = None
    # The file the thread is on.
    path: str = ""
    # GitHub failed to return the replies between the first one and the newest hundred.
    older_replies_unread: bool = False
    # The login of whoever resolved it, as the host reports it, and whether that was the change's author.
    resolved_by: str | None = None
    resolved_by_pr_author: bool = False


OutcomeStatus = Literal["open", "fixed", "muted", "resolved", "suppressed"]
OUTCOME_STATUSES: tuple[OutcomeStatus, ...] = get_args(OutcomeStatus)


@dataclass(frozen=True, slots=True)
class Outcome:
    """What happened to one finding on a pull request so far (ADR 0022).

    `fixed`: it went away while the model read its file. `muted`: a maintainer replied `bylaw: ignore`.
    `resolved`: someone other than the author resolved its thread with the finding still there.
    `suppressed`: a suppression in .bylaw.toml hid it. `open`: none of these.
    """

    status: OutcomeStatus
    category: str
    # The evidence it cites, as a suppression would name it; None for a finding that cites nothing.
    rule: str | None
    file: str
    # The maintainer who muted it or the person who resolved its thread.
    by: str | None = None


@dataclass(frozen=True, slots=True)
class State:
    # Ids of the threads bylaw resolved itself. States saved before this held fingerprints instead.
    auto_resolved: frozenset[str]
    # What the last model review saw and said, for an incremental review (ADR 0012).
    review: ReviewMemory | None = None
    # Fingerprint to what happened to that finding on this pull request, for learning (ADR 0022).
    outcomes: Mapping[str, Outcome] = field(default_factory=dict)
    # How many criteria the last run found met, partial, missing and not assessed.
    criteria: Mapping[str, int] = field(default_factory=dict)


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
    # Resolved by the pull request's author while the finding is still there: open all the same (ADR 0008).
    author_resolved: tuple[Group, ...] = ()
    # Notes publishing adds, such as threads read without their older replies: the summary and the
    # evidence read them from here, so both say the same.
    notes: tuple[str, ...] = ()
    # Hidden by a suppression in .bylaw.toml: listed in the summary, never posted or counted (ADR 0022).
    suppressed: tuple[Group, ...] = ()


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


def make_plan(  # noqa: PLR0913 - every argument is a distinct input to one decision
    groups: Sequence[Group],
    threads: Sequence[Thread],
    state: State,
    threshold: Severity,
    cap: int,
    *,
    unreviewed: frozenset[str] = frozenset(),
) -> Plan:
    ours: dict[str, list[Thread]] = {}
    for thread in threads:
        # ADR 0008: a fingerprint counts only in a comment bylaw or a maintainer could have written.
        # bylaw writes its marker last, so an earlier one quoted in the message cannot take its place.
        if (
            thread.comments
            and thread.comments[0].trusted
            and (found := FINGERPRINT.findall(thread.comments[0].body))
        ):
            ours.setdefault(found[-1], []).append(thread)

    paired, unpaired = _pair(groups, ours)
    # A thread on a file the model did not read this run is not evidence of a fix (ADR 0012).
    fixed = [(fp, t) for fp, t in unpaired if not t.resolved and t.path not in unreviewed]
    auto_resolved = set(state.auto_resolved) | {thread.id for _, thread in fixed}

    inline: list[Group] = []
    summary_only: list[Group] = []
    muted: list[Group] = []
    reviewer_resolved: list[Group] = []
    author_resolved: list[Group] = []
    open_threads: list[Group] = []
    unresolve: list[str] = []
    for index, group in sorted(enumerate(groups), key=lambda item: _order(item[1])):
        existing = paired.get(index)
        if existing is None:
            if _RANK[group.finding.severity] > _RANK[threshold] or len(inline) >= cap:
                summary_only.append(group)
            else:
                inline.append(group)
        elif mute := next((reply for reply in existing.comments[1:] if _mutes(reply)), None):
            muted.append(replace(group, by=mute.author or None))
        elif existing.resolved and _resolved_by_bylaw(existing, group.fingerprint, auto_resolved, ours):
            unresolve.append(existing.id)
            auto_resolved.discard(existing.id)
            auto_resolved.discard(group.fingerprint)
            open_threads.append(group)
        elif existing.resolved and existing.resolved_by_pr_author:
            author_resolved.append(replace(group, by=existing.resolved_by))
        elif existing.resolved:
            reviewer_resolved.append(replace(group, by=existing.resolved_by))
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
        state=State(auto_resolved=frozenset(auto_resolved & {t.id for ts in ours.values() for t in ts})),
        author_resolved=tuple(author_resolved),
    )


_FAR = 10**9


def _distance(thread: Thread, finding: Finding) -> int:
    # GitHub's `line` is the end line of a comment, and bylaw anchors comments on `line_end`.
    if thread.line is not None:
        return abs(thread.line - finding.line_end)
    if thread.original_line is not None:
        return _FAR + abs(thread.original_line - finding.line_end)
    return 2 * _FAR


def _resolved_by_bylaw(
    thread: Thread, fp: str, auto_resolved: set[str], ours: Mapping[str, list[Thread]]
) -> bool:
    # A fingerprint from an older state is trusted only when it names a single thread.
    return thread.id in auto_resolved or (fp in auto_resolved and len(ours.get(fp, [])) == 1)


def _pair(
    groups: Sequence[Group], ours: Mapping[str, list[Thread]]
) -> tuple[dict[int, Thread], list[tuple[str, Thread]]]:
    """Match findings to their threads; findings on identical lines share a fingerprint, so line decides.

    Nearest line first, outdated threads last. A mute or resolve stays with the code it was written about:
    deleting one copy resolves that copy's thread and never hands its mute to another. Between threads on
    the same line, the one whose comment states the finding's message wins, so two problems on one line
    keep their own threads whichever order the model lists them in (HRD-36). A reworded finding still
    pairs by line, so threads posted before keep their mutes.
    """
    indexes: dict[str, list[int]] = {}
    for index, group in enumerate(groups):
        indexes.setdefault(group.fingerprint, []).append(index)
    paired: dict[int, Thread] = {}
    unpaired: list[tuple[str, Thread]] = []
    for fp, candidates in ours.items():
        options = sorted(
            (_distance(thread, finding := groups[index].finding), not _says(thread, finding), index, n)
            for index in indexes.get(fp, [])
            for n, thread in enumerate(candidates)
        )
        used: set[int] = set()
        for *_, index, n in options:
            if index in paired or n in used:
                continue
            paired[index] = candidates[n]
            used.add(n)
        unpaired += [(fp, thread) for n, thread in enumerate(candidates) if n not in used]
    return paired, unpaired


def _says(thread: Thread, finding: Finding) -> bool:
    """Whether the thread's first comment is bylaw's inline comment for this message (render.inline_parts).

    The comment escapes `&`, `<` and `>` as entities and puts a zero-width space after `@`; both are undone
    here, and so is the zero-width space GitLab comments put before a leading `/`.
    """
    _, _, text = thread.comments[0].body.partition("** ")
    text = html.unescape(text).replace(_ZERO_WIDTH_SPACE, "")
    return text == finding.message or text.startswith(f"{finding.message}\n\n")


def suppressed_by(finding: Finding, suppressions: Iterable[Suppression]) -> Suppression | None:
    """The suppression that hides a finding: it must cite the suppression's rule, exactly, in one of its
    paths. A security finding is never hidden (ADR 0022)."""
    if finding.category == Category.SECURITY or finding.evidence is None:
        return None
    path = PurePosixPath(finding.file)
    return next(
        (s for s in suppressions if s.rule == finding.evidence and any(path.full_match(p) for p in s.paths)),
        None,
    )


def remaining(plan: Plan) -> tuple[Finding, ...]:
    """Findings still standing after a run: a maintainer's mute or resolve takes a finding out, the pull
    request author's resolve does not (ADR 0008)."""
    groups = (*plan.inline, *plan.open_threads, *plan.summary_only, *plan.author_resolved)
    return tuple(finding for group in groups for finding in (group.finding, *group.others))


def track_outcomes(
    previous: Mapping[str, Outcome], plan: Plan, unreviewed: frozenset[str] = frozenset()
) -> dict[str, Outcome]:
    """What happened to each finding so far: this run's plan over the last run's outcomes (ADR 0022).

    A mute or a resolve stays, even when the code changes later: the maintainer's call was made. A
    finding that is gone counts as fixed only when the model read its file this run (ADR 0012).
    """
    current: dict[str, Outcome] = {}
    by_status: tuple[tuple[OutcomeStatus, tuple[Group, ...]], ...] = (
        ("open", (*plan.inline, *plan.open_threads, *plan.summary_only, *plan.author_resolved)),
        ("muted", plan.muted),
        ("resolved", plan.reviewer_resolved),
        ("suppressed", plan.suppressed),
    )
    for status, groups in by_status:
        for group in groups:
            finding = group.finding
            by = group.by if status in ("muted", "resolved") else None
            current[group.fingerprint] = Outcome(status, finding.category, finding.evidence, finding.file, by)
    for fp, old in previous.items():
        if fp in current and not (old.status in ("muted", "resolved") and current[fp].status == "open"):
            continue
        gone = old.status == "open" and old.file not in unreviewed
        current[fp] = replace(old, status="fixed") if gone else old
    return current


def close_outcomes(
    outcomes: Mapping[str, Outcome], threads: Sequence[Thread], auto_resolved: frozenset[str]
) -> dict[str, Outcome]:
    """The outcomes when the pull request closes: a mute or resolve made after the last run counts too.

    The same trust rules as a run: the thread must open with a trusted fingerprint, a mute must come from
    a maintainer who is not the author, and a resolve by the author or by bylaw itself accepts nothing.
    """
    closed = dict(outcomes)
    for thread in threads:
        first = thread.comments[0] if thread.comments else None
        found = FINGERPRINT.findall(first.body) if first and first.trusted else []
        if not found or (old := closed.get(found[-1])) is None or old.status != "open":
            continue
        if mute := next((reply for reply in thread.comments[1:] if _mutes(reply)), None):
            closed[found[-1]] = replace(old, status="muted", by=mute.author or None)
        elif thread.resolved and not thread.resolved_by_pr_author and thread.id not in auto_resolved:
            closed[found[-1]] = replace(old, status="resolved", by=thread.resolved_by)
    return closed


def _mutes(reply: ThreadComment) -> bool:
    """A maintainer can mute a finding, but not on their own pull request (ADR 0008)."""
    return reply.trusted and not reply.by_pr_author and bool(_IGNORE.search(reply.body))


def _order(group: Group) -> tuple[int, str, int]:
    return _RANK[group.finding.severity], group.finding.file, group.finding.line_start
