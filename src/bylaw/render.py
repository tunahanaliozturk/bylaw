"""Markdown for the inline comments and the summary, and the hidden state the summary carries.

Every string that came from a pull request, a spec or a model passes through `_text` or `_code` before
it is rendered, so it cannot open an HTML comment, close a section or plant a bylaw marker.
"""

import json
import re
from collections import Counter
from collections.abc import Iterable

from bylaw.model import CriterionResult, Location, ReviewContext, ReviewResult, Severity
from bylaw.plan import Group, Plan, State

SUMMARY_MARKER = "<!-- bylaw:summary -->"
MAX_BODY = 65_536
_STATE_OPEN = "<!-- bylaw:state "
_STATE = re.compile(r"<!-- bylaw:state (\{.*\}) -->\s*", re.DOTALL)
# ponytail: about 20 KB of hashes. Entries are already limited to threads that still exist; past the
# ceiling the cut is by hash order, which only means a few fixed findings forget they were auto-resolved.
_MAX_STATE_ENTRIES = 1000
_MAX_PLACES = 5
_TRIMMED = "\n\n_Summary trimmed to fit GitHub's comment size limit._"
_MAX_CELL = 80
# A criterion is the one cell a reader needs whole; inferred ones are capped at 300 characters (validate).
_CRITERION_CELL = 300
_BACKTICKS = re.compile(r"`+")


def inline_body(group: Group) -> str:
    finding = group.finding
    parts = [f"**{finding.category} · {finding.severity}** {_text(finding.message)}"]
    if finding.evidence:
        parts.append(f"Evidence: {_code(finding.evidence)}")
    if finding.suggestion is not None:
        # The fence must be longer than any backtick run inside, or the suggestion closes it early.
        longest = max((len(run) for run in _BACKTICKS.findall(finding.suggestion)), default=0)
        fence = "`" * max(3, longest + 1)
        parts.append(f"{fence}suggestion\n{finding.suggestion}\n{fence}")
    if group.others:
        places = ", ".join(_code(f"{other.file}:{other.line_start}") for other in group.others[:_MAX_PLACES])
        more = f" and {len(group.others) - _MAX_PLACES} more" if len(group.others) > _MAX_PLACES else ""
        parts.append(f"Also at {places}{more}.")
    parts.append(f"<!-- bylaw:fp={group.fingerprint} -->")
    return "\n\n".join(parts)


def review_body(plan: Plan) -> str:
    count = len(plan.inline)
    plural = "s" if count != 1 else ""
    return f"bylaw left {count} new comment{plural}. The summary comment has the full picture."


def summary_body(context: ReviewContext, result: ReviewResult, plan: Plan) -> str:
    current = [*plan.inline, *plan.open_threads, *plan.summary_only, *plan.reviewer_resolved]
    sections = [
        SUMMARY_MARKER,
        "## bylaw review",
        _headline(context, plan, current),
        _requirements(context, result),
        _scope_creep(result),
        _details("Other findings", plan.summary_only),
        _details("Resolved by a reviewer but still present", plan.reviewer_resolved),
        _details("Muted with `bylaw: ignore`", plan.muted),
        _rule_sources(context),
        _notes(context),
    ]
    body = "\n\n".join(section for section in sections if section)
    entries = sorted(plan.state.auto_resolved)[-_MAX_STATE_ENTRIES:]
    state = "\n\n" + _STATE_OPEN + json.dumps({"auto_resolved": entries}) + " -->"
    room = MAX_BODY - len(state)
    if len(body) > room:
        body = body[: room - len(_TRIMMED)] + _TRIMMED
    return body + state


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
    entries = raw.get("auto_resolved", []) if isinstance(raw, dict) else []
    return State(auto_resolved=frozenset(e for e in entries if isinstance(e, str)))


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
        if not listed:
            rows.append(
                f"| {_code(requirement.source)} {_cell(requirement.title)} | no criteria listed |  |  |"
            )
        for key, text in listed:
            item: CriterionResult | None = results.get(key)
            status = item.status.value if item else "not assessed"
            if item and item.note:
                status = f"{status}: {_cell(item.note)}"
            code = _locations(item.code) if item else ""
            tests = _locations(item.tests) if item else ""
            rows.append(f"| {_code(key)} {text} | {status} | {code} | {tests} |")
    return "### Requirements\n\n" + "\n".join(rows)


def _scope_creep(result: ReviewResult) -> str:
    if not result.scope_creep:
        return ""
    lines = [
        f"- {_code(f'{entry.file}:{entry.line}')} {_text(entry.message)}" for entry in result.scope_creep
    ]
    return "### Scope creep\n\n" + "\n".join(lines)


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
    if not context.rules:
        return ""
    paths = "\n".join(f"- {_code(rule.path)}" for rule in context.rules)
    return f"<details><summary>Rule sources ({len(context.rules)})</summary>\n\n{paths}\n\n</details>"


def _notes(context: ReviewContext) -> str:
    if not context.notes:
        return ""
    return "### Notes\n\n" + "\n".join(f"- {_text(note)}" for note in context.notes)


def _locations(locations: Iterable[Location]) -> str:
    return ", ".join(_code(f"{location.file}:{location.line}") for location in locations)


def _cell(text: str, limit: int = _MAX_CELL) -> str:
    # Cut before escaping, so a limit never lands inside an entity such as &amp;.
    flat = " ".join(text.split())
    cut = flat if len(flat) <= limit else flat[: limit - 3] + "..."
    return _text(cut).replace("|", "\\|")


def _text(text: str) -> str:
    """Prose from outside bylaw: angle brackets become entities, so no HTML or comment can open."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _code(text: str) -> str:
    """A path or reference in a code span; anything that could escape the span is rendered as prose."""
    if "`" in text or "<" in text or "\n" in text:
        return _text(text)
    return f"`{text}`"
