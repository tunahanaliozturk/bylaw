"""Markdown for the inline comments and the summary, and the hidden state the summary carries.

Every string that came from a pull request, a spec or a model passes through `_text` or `_code` before
it is rendered, so it cannot open an HTML comment, close a section or plant a bylaw marker.
"""

import json
import re
from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from pydantic import ValidationError

from bylaw.evidence import DISCLAIMER, Evidence, EvidenceFinding, EvidenceRequirement, build_evidence
from bylaw.model import (
    CriterionResult,
    CriterionStatus,
    Location,
    ReviewContext,
    ReviewMemory,
    ReviewResult,
    Severity,
)
from bylaw.plan import OUTCOME_STATUSES, Group, Outcome, Plan, State, suppressed_by

SUMMARY_MARKER = "<!-- bylaw:summary -->"
MAX_BODY = 65_536
_STATE_OPEN = "<!-- bylaw:state "
_STATE = re.compile(r"<!-- bylaw:state (\{.*\}) -->\s*", re.DOTALL)
# ponytail: about 20 KB of hashes. Entries are already limited to threads that still exist; past the
# ceiling the cut is by hash order, which only means a few fixed findings forget they were auto-resolved.
_MAX_STATE_ENTRIES = 1000
# ponytail: the review memory (ADR 0012) gets at most this much of the comment; a bigger one is left out
# and the next run reviews everything, which costs tokens but never loses a finding.
_MAX_MEMORY = 20_000
# ponytail: outcomes (ADR 0022) get at most this much; past it the open and fixed ones are dropped first,
# which only makes the report count fewer of them. About 120 entries with ordinary paths.
_MAX_OUTCOMES = 12_000
_OUTCOME_FIELDS = ("status", "category", "rule", "file", "by")
_MAX_PLACES = 5
_TRIMMED = "\n\n_Summary trimmed to fit the comment size limit._"
_MAX_CELL = 80
# A criterion is the one cell a reader needs whole; inferred ones are capped at 300 characters (validate).
_CRITERION_CELL = 300
_BACKTICKS = re.compile(r"`+")


@dataclass(frozen=True, slots=True)
class InlineParts:
    """An inline comment as rendered: the prose before the suggestion, the suggestion's own text, and the
    prose after it. A host that writes suggestions differently (GitLab) builds the block from these."""

    before: str
    suggestion: str | None
    after: str


def inline_parts(group: Group) -> InlineParts:
    finding = group.finding
    before = [f"**{finding.category} · {finding.severity}** {_text(finding.message)}"]
    if finding.evidence:
        before.append(f"Evidence: {_code(finding.evidence)}")
    if finding.controls:
        before.append("Controls: " + ", ".join(_code(control) for control in finding.controls))
    after: list[str] = []
    if group.others:
        places = ", ".join(_code(f"{other.file}:{other.line_start}") for other in group.others[:_MAX_PLACES])
        more = f" and {len(group.others) - _MAX_PLACES} more" if len(group.others) > _MAX_PLACES else ""
        after.append(f"Also at {places}{more}.")
    after.append(f"<!-- bylaw:fp={group.fingerprint} -->")
    return InlineParts("\n\n".join(before), finding.suggestion, "\n\n".join(after))


def suggestion_block(text: str, info: str = "suggestion") -> str:
    # The fence must be longer than any backtick run inside, or the suggestion closes it early.
    longest = max((len(run) for run in _BACKTICKS.findall(text)), default=0)
    fence = "`" * max(3, longest + 1)
    return f"{fence}{info}\n{text}\n{fence}"


def inline_body(group: Group) -> str:
    parts = inline_parts(group)
    block = suggestion_block(parts.suggestion) if parts.suggestion is not None else ""
    return "\n\n".join(part for part in (parts.before, block, parts.after) if part)


def review_body(plan: Plan) -> str:
    count = len(plan.inline)
    plural = "s" if count != 1 else ""
    return f"bylaw left {count} new comment{plural}. The summary comment has the full picture."


def summary_body(context: ReviewContext, result: ReviewResult, plan: Plan) -> str:
    current = [
        *plan.inline,
        *plan.open_threads,
        *plan.summary_only,
        *plan.author_resolved,
        *plan.reviewer_resolved,
    ]
    sections = [
        SUMMARY_MARKER,
        "## bylaw review",
        _headline(context, plan, current),
        _requirements(context, result),
        _scope_creep(result),
        # Before the long sections: a trimmed summary must keep the notes the other sections point to.
        _notes((*context.notes, *plan.notes)),
        _suppressions(context, plan),
        *_compliance(context, result, plan),
        _details("Other findings", plan.summary_only),
        # Posted on an earlier run: listed here too, so a finding is never only in a thread nobody opens.
        _details("Open in a review thread", plan.open_threads),
        _details("Resolved by the pull request's author but still present", plan.author_resolved),
        _details("Resolved by a reviewer but still present", plan.reviewer_resolved),
        _details("Muted with `bylaw: ignore`", plan.muted),
        _details("Hidden by a suppression", plan.suppressed),
        _rule_sources(context),
        _footer(plan.state.review),
    ]
    body = "\n\n".join(section for section in sections if section)
    state = "\n\n" + _STATE_OPEN + _state_json(plan.state) + " -->"
    room = max(0, MAX_BODY - len(state))
    if len(body) > room:
        body = body[: room - len(_TRIMMED)] + _TRIMMED
    return body + state


def tokens_only(memory: ReviewMemory) -> ReviewMemory:
    """The memory without what it reviewed: the next run reviews everything but the budget still counts."""
    return ReviewMemory(
        head_sha=memory.head_sha, inputs=memory.inputs, tokens=memory.tokens, run_tokens=memory.run_tokens
    )


def _state_json(state: State) -> str:
    raw: dict[str, object] = {"auto_resolved": sorted(state.auto_resolved)[-_MAX_STATE_ENTRIES:]}
    if state.review is not None:
        raw["review"] = state.review.model_dump(mode="json")
        if len(_escaped(raw["review"])) > _MAX_MEMORY:
            raw["review"] = tokens_only(state.review).model_dump(mode="json")
    if state.outcomes:
        raw["outcomes"] = _outcomes_within_budget(state.outcomes)
    if state.criteria:
        raw["criteria"] = dict(state.criteria)
    return _escaped(raw)


def _outcomes_within_budget(outcomes: Mapping[str, Outcome]) -> dict[str, list[str | None]]:
    """As many outcomes as fit `_MAX_OUTCOMES`, mutes and resolves first: they are what learning counts."""
    ranked = sorted(outcomes.items(), key=lambda item: (item[1].status not in ("muted", "resolved"), item[0]))
    kept: dict[str, list[str | None]] = {}
    size = 0
    for fp, o in ranked:
        entry = [o.status, o.category, o.rule, o.file, o.by]
        # ponytail: the escaped length of one entry plus its key and separators, summed; a little over
        # the true size of the object, never under it.
        cost = len(_escaped({fp: entry}))
        if size + cost > _MAX_OUTCOMES:
            continue
        kept[fp] = entry
        size += cost
    return kept


def _escaped(raw: object) -> str:
    # Model text sits in the memory; with < and > escaped it cannot close the comment the state lives in.
    return json.dumps(raw).replace("<", "\\u003c").replace(">", "\\u003e")


def read_state(body: str) -> State:
    """ADR 0005: unreadable state counts as empty, which is noisy but never loses a finding.

    Only the state block that ends the comment counts; bylaw always writes it last.
    """
    empty = State(auto_resolved=frozenset())
    start = body.rfind(_STATE_OPEN)
    match = _STATE.fullmatch(body, start) if start != -1 else None
    if match is None:
        return empty
    try:
        raw = json.loads(match[1])
    except ValueError:
        return empty
    if not isinstance(raw, dict):
        return empty
    entries = raw.get("auto_resolved", [])
    auto = frozenset(e for e in entries if isinstance(e, str)) if isinstance(entries, list) else frozenset()
    review = None
    if "review" in raw:
        try:
            review = ReviewMemory.model_validate(raw["review"])
        except ValidationError:
            review = None  # an unreadable memory only means the next run reviews everything
    criteria = raw.get("criteria")
    counts = (
        {k: v for k, v in criteria.items() if isinstance(v, int) and not isinstance(v, bool)}
        if isinstance(criteria, dict)
        else {}
    )
    return State(
        auto_resolved=auto, review=review, outcomes=_read_outcomes(raw.get("outcomes")), criteria=counts
    )


def _read_outcomes(raw: object) -> dict[str, Outcome]:
    """Each entry is `[status, category, rule, file, by]`; one that does not read so is left out."""
    outcomes: dict[str, Outcome] = {}
    for fp, entry in raw.items() if isinstance(raw, dict) else ():
        if not (isinstance(entry, list) and len(entry) == len(_OUTCOME_FIELDS)):
            continue
        status, category, rule, file, by = entry
        if (
            status in OUTCOME_STATUSES
            and isinstance(category, str)
            and isinstance(file, str)
            and (rule is None or isinstance(rule, str))
            and (by is None or isinstance(by, str))
        ):
            outcomes[fp] = Outcome(status, category, rule, file, by)
    return outcomes


def _headline(context: ReviewContext, plan: Plan, current: list[Group]) -> str:
    counts = Counter(group.finding.severity for group in current)
    by_severity = ", ".join(f"{counts[s]} {s}" for s in Severity if counts[s]) or "no findings"
    new = len(plan.inline)
    return (
        f"Reviewed {_code(context.head_sha[:7])} against {_code(context.base_sha[:7])}: {by_severity}. "
        f"{new} new inline comment{'s' if new != 1 else ''} this run, {len(plan.resolve)} thread(s) resolved."
    )


def _requirements(context: ReviewContext, result: ReviewResult) -> str:
    if not context.requirements:
        return "### Requirements\n\nNo linked issue or spec was found."
    results = {item.criterion: item for item in result.criteria}
    rows = ["| Criterion | Status | Code | Tests |", "| --- | --- | --- | --- |"]
    for requirement in context.requirements:
        listed = [
            (f"{requirement.source}/{c.key}", _cell(c.text, _CRITERION_CELL)) for c in requirement.criteria
        ]
        # ADR 0011: criteria the reviewer inferred from prose or maintainer comments follow, marked.
        prefix = f"{requirement.source}/IC-"
        inferred = sorted(
            (item for key, item in results.items() if key.startswith(prefix)),
            key=lambda item: int(item.criterion.removeprefix(prefix)),
        )
        listed += [
            (item.criterion, f"{_cell(item.text or '', _CRITERION_CELL)} (inferred)") for item in inferred
        ]
        # ADR 0014: a work item kept out of quotes shows keys, status and places, never its words or the
        # reviewer's note, which may repeat them.
        quoted = requirement.quoted
        if not quoted:
            listed = [(key, "(inferred)" if key.startswith(prefix) else "") for key, _ in listed]
        if not listed:
            title = f" {_cell(requirement.title)}" if quoted else ""
            rows.append(f"| {_code(requirement.source)}{title} | no criteria listed |  |  |")
        for key, text in listed:
            item: CriterionResult | None = results.get(key)
            status = item.status.value if item else "not assessed"
            if item and item.note and quoted:
                status = f"{status}: {_cell(item.note)}"
            code = _locations(item.code) if item else ""
            tests = _locations(item.tests) if item else ""
            label = f"{_code(key)} {text}" if text else _code(key)
            rows.append(f"| {label} | {status} | {code} | {tests} |")
    return "### Requirements\n\n" + "\n".join(rows)


def _scope_creep(result: ReviewResult) -> str:
    if not result.scope_creep:
        return ""
    lines = [
        f"- {_code(f'{entry.file}:{entry.line}')} {_text(entry.message)}" for entry in result.scope_creep
    ]
    return "### Scope creep\n\n" + "\n".join(lines)


def _compliance(context: ReviewContext, result: ReviewResult, plan: Plan) -> list[str]:
    """ADR 0021: the controls the findings touch and the change-management record, when a profile is on."""
    if not context.profiles:
        return []
    record = build_evidence(context, result, plan)
    return [_controls_touched(record), _change_management(record)]


def _controls_touched(record: Evidence) -> str:
    standards = "; ".join(f"{_code(p.name)}, {_text(p.standard)}" for p in record.profiles)
    head = f"### Controls touched\n\nProfile {standards}. {DISCLAIMER}"
    if not record.controls:
        return f"{head}\n\nNo finding touches a control of the profile."
    rows = ["| Control | Findings |", "| --- | --- |"]
    for control in record.controls:
        touching = [f for f in record.findings if control.id in f.controls]
        places = [f"{_code(f'{f.file}:{f.line_start}')} {f.severity}, {f.status}" for f in touching]
        rows.append(f"| {_code(control.id)} {_cell(control.title)} | {_listed(places, '; ')} |")
    return f"{head}\n\n" + "\n".join(rows)


def _change_management(record: Evidence) -> str:
    requirements = "; ".join(f"{_code(r.source)}, {_criteria_met(r)}" for r in record.requirements)
    model = {
        True: "with the model review",
        False: "without calling the model on it (see the notes)",
        None: "and the result came from outside `bylaw review`, such as a host model, so bylaw cannot say "
        "whether a model read it",
    }[record.model_review]
    tests = _listed([_code(t.path) for t in record.tests_changed if t.status != "removed"], ", ")
    removed = _listed([_code(t.path) for t in record.tests_changed if t.status == "removed"], ", ")
    accepted = [f for f in record.findings if f.status == "accepted"]
    suppressed = sum(f.status == "suppressed" for f in record.findings)
    opened = len(record.findings) - len(accepted) - suppressed
    threads = f"{record.threads_resolved} thread{'s' if record.threads_resolved != 1 else ''}"
    lines = [
        f"- Requirements: {requirements or 'none linked'}.",
        f"- Reviewed: {_code(record.head_sha[:7])} against {_code(record.base_sha[:7])}, {model}.",
        f"- Tests changed: {tests or 'none'}.",
        *([f"- Tests removed: {removed}."] if removed else []),
        f"- Findings: {opened} open, {len(accepted)} accepted, {threads} resolved as fixed this run.",
        *([f"- Hidden by a suppression in `.bylaw.toml`: {suppressed}."] if suppressed else []),
    ]
    if accepted:
        lines.append("- Accepted: " + _listed([_acceptance(f) for f in accepted], "; ") + ".")
    if by_author := [f for f in record.findings if f.status == "resolved_by_author"]:
        lines.append("- Still open: " + _listed([_acceptance(f) for f in by_author], "; ") + ".")
    return "### Change management evidence\n\n" + "\n".join(lines)


def _criteria_met(requirement: EvidenceRequirement) -> str:
    if not requirement.criteria:
        return "no criteria"
    met = sum(c.status == CriterionStatus.MET for c in requirement.criteria)
    return f"{met} of {len(requirement.criteria)} criteria met"


def _acceptance(finding: EvidenceFinding) -> str:
    where = _code(f"{finding.file}:{finding.line_start}")
    who = f" by {_code(finding.by)}" if finding.by else ""
    if finding.status == "resolved_by_author":
        author = f" {_code(finding.by)}" if finding.by else ""
        return f"{where} resolved by its author{author}, which does not accept it"
    if finding.how == "muted":
        return f"{where} muted{who or ' by a maintainer'} with `bylaw: ignore`"
    return f"{where} resolved{who or ' by a reviewer'}"


def _listed(items: list[str], separator: str) -> str:
    more = f"{separator}and {len(items) - _MAX_PLACES} more" if len(items) > _MAX_PLACES else ""
    return separator.join(items[:_MAX_PLACES]) + more


def _suppressions(context: ReviewContext, plan: Plan) -> str:
    """ADR 0022: every suppression in force is listed, with how much it hid, so none works unseen."""
    if not context.suppressions:
        return ""
    hidden = Counter(
        suppressed_by(finding, context.suppressions)
        for group in plan.suppressed
        for finding in (group.finding, *group.others)
    )
    lines = []
    for suppression in context.suppressions:
        count = hidden[suppression]
        paths = ", ".join(_code(path) for path in suppression.paths)
        lines.append(
            f"- {_code(suppression.rule)} in {paths}: {_text(suppression.reason)} "
            f"Hid {count} finding{'s' if count != 1 else ''} this run."
        )
    return (
        "### Suppressions\n\n`.bylaw.toml` on the base branch hides some findings. A suppression only "
        "hides a finding that cites its rule in its paths, and never a security finding.\n\n"
        + "\n".join(lines)
    )


def _details(title: str, groups: Iterable[Group]) -> str:
    items = [_detail_line(g) for g in groups]
    if not items:
        return ""
    return f"<details><summary>{title} ({len(items)})</summary>\n\n" + "\n".join(items) + "\n\n</details>"


def _detail_line(group: Group) -> str:
    finding = group.finding
    where = _code(f"{finding.file}:{finding.line_start}")
    evidence = f" ({_code(finding.evidence)})" if finding.evidence else ""
    return f"- **{finding.category} · {finding.severity}** {where} {_text(finding.message)}{evidence}"


def _rule_sources(context: ReviewContext) -> str:
    sources = [rule.path for rule in context.rules] + [decision.path for decision in context.decisions]
    if not sources:
        return ""
    paths = "\n".join(f"- {_code(path)}" for path in sources)
    return f"<details><summary>Rule sources ({len(sources)})</summary>\n\n{paths}\n\n</details>"


def _notes(notes: tuple[str, ...]) -> str:
    if not notes:
        return ""
    return "### Notes\n\n" + "\n".join(f"- {_text(note)}" for note in notes)


def _footer(memory: ReviewMemory | None) -> str:
    if memory is None or not memory.tokens:
        return ""
    return f"<sub>Model tokens: {memory.run_tokens:,} this run, {memory.tokens:,} on this pull request.</sub>"


def _locations(locations: Iterable[Location]) -> str:
    return ", ".join(_code(f"{location.file}:{location.line}") for location in locations)


def _cell(text: str, limit: int = _MAX_CELL) -> str:
    # Cut before escaping, so a limit never lands inside an entity such as &amp;.
    flat = " ".join(text.split())
    cut = flat if len(flat) <= limit else flat[: limit - 3] + "..."
    return _text(cut).replace("|", "\\|")


def _text(text: str) -> str:
    """Prose from outside bylaw: angle brackets become entities, so no HTML or comment can open, and a
    zero-width space follows every `@`, so quoted text cannot mention a person or a team."""
    escaped = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return escaped.replace("@", "@&#8203;")


def _code(text: str) -> str:
    """A path or reference in a code span; anything that could escape the span is rendered as prose."""
    if "`" in text or "<" in text or "\n" in text:
        return _text(text)
    return f"`{text}`"


def code_span(text: str) -> str:
    """`_code` for the other Markdown bylaw writes, such as a suggestion pull request's body."""
    return _code(text)
