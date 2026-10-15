"""Markdown for the inline comments and the summary, and the hidden state the summary carries."""

import json
import re
from collections import Counter
from collections.abc import Iterable

from bylaw.model import CriterionResult, Location, ReviewContext, ReviewResult, Severity
from bylaw.plan import Group, Plan, State

SUMMARY_MARKER = "<!-- bylaw:summary -->"
MAX_BODY = 65_536
_STATE = re.compile(r"<!-- bylaw:state (\{.*?\}) -->", re.DOTALL)
_MAX_STATE_ENTRIES = 1000  # ponytail: about 20 KB of hashes; older entries drop off first.
_MAX_PLACES = 5
_TRIMMED = "\n\n_Summary trimmed to fit GitHub's comment size limit._"
_MAX_CELL = 80


def inline_body(group: Group) -> str:
    finding = group.finding
    parts = [f"**{finding.category} · {finding.severity}** {finding.message}"]
    if finding.evidence:
        parts.append(f"Evidence: `{finding.evidence}`")
    if finding.suggestion is not None:
        fence = "````" if "```" in finding.suggestion else "```"
        parts.append(f"{fence}suggestion\n{finding.suggestion}\n{fence}")
    if group.others:
        places = ", ".join(f"`{other.file}:{other.line_start}`" for other in group.others[:_MAX_PLACES])
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
    state = "\n\n<!-- bylaw:state " + json.dumps({"auto_resolved": entries}) + " -->"
    room = MAX_BODY - len(state)
    if len(body) > room:
        body = body[: room - len(_TRIMMED)] + _TRIMMED
    return body + state


def read_state(body: str) -> State:
    """ADR 0005: unreadable state counts as empty, which is noisy but never loses a finding."""
    match = _STATE.search(body)
    if match is None:
        return State(auto_resolved=frozenset())
    try:
        raw = json.loads(match[1])
    except ValueError:
        return State(auto_resolved=frozenset())
    entries = raw.get("auto_resolved", []) if isinstance(raw, dict) else []
    return State(auto_resolved=frozenset(e for e in entries if isinstance(e, str)))


def _headline(context: ReviewContext, plan: Plan, current: list[Group]) -> str:
    counts = Counter(group.finding.severity for group in current)
    by_severity = ", ".join(f"{counts[s]} {s}" for s in Severity if counts[s]) or "no findings"
    new = len(plan.inline)
    return (
        f"Reviewed `{context.head_sha[:7]}` against `{context.base_sha[:7]}`: {by_severity}. "
        f"{new} new inline comment{'s' if new != 1 else ''} this run, {len(plan.resolve)} thread(s) resolved."
    )


def _requirements(context: ReviewContext, result: ReviewResult) -> str:
    if not context.requirements:
        return "### Requirements\n\nNo linked issue or spec was found."
    results = {item.criterion: item for item in result.criteria}
    rows = ["| Criterion | Status | Code | Tests |", "| --- | --- | --- | --- |"]
    for requirement in context.requirements:
        for criterion in requirement.criteria:
            key = f"{requirement.source}/{criterion.key}"
            item: CriterionResult | None = results.get(key)
            status = item.status.value if item else "not assessed"
            code = _locations(item.code) if item else ""
            tests = _locations(item.tests) if item else ""
            rows.append(f"| `{key}` {_cell(criterion.text)} | {status} | {code} | {tests} |")
    return "### Requirements\n\n" + "\n".join(rows)


def _scope_creep(result: ReviewResult) -> str:
    if not result.scope_creep:
        return ""
    lines = [f"- `{entry.file}:{entry.line}` {entry.message}" for entry in result.scope_creep]
    return "### Scope creep\n\n" + "\n".join(lines)


def _details(title: str, groups: Iterable[Group]) -> str:
    items = [
        f"- **{g.finding.category} · {g.finding.severity}** `{g.finding.file}:{g.finding.line_start}` "
        f"{g.finding.message}" + (f" ({g.finding.evidence})" if g.finding.evidence else "")
        for g in groups
    ]
    if not items:
        return ""
    return f"<details><summary>{title} ({len(items)})</summary>\n\n" + "\n".join(items) + "\n\n</details>"


def _rule_sources(context: ReviewContext) -> str:
    if not context.rules:
        return ""
    paths = "\n".join(f"- `{rule.path}`" for rule in context.rules)
    return f"<details><summary>Rule sources ({len(context.rules)})</summary>\n\n{paths}\n\n</details>"


def _notes(context: ReviewContext) -> str:
    if not context.notes:
        return ""
    return "### Notes\n\n" + "\n".join(f"- {note}" for note in context.notes)


def _locations(locations: Iterable[Location]) -> str:
    return ", ".join(f"`{location.file}:{location.line}`" for location in locations)


def _cell(text: str) -> str:
    flat = " ".join(text.split()).replace("|", "\\|")
    return flat if len(flat) <= _MAX_CELL else flat[: _MAX_CELL - 3] + "..."
