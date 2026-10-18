"""The Markdown report README numbers are quoted from."""

from collections.abc import Sequence

from bylaw.evaluation.cases import Case
from bylaw.evaluation.run import CaseRun
from bylaw.evaluation.score import Score, score

_REAL = (
    "Real pull requests, frozen at the commit a reviewer commented on (ADR 0015). Scored with the same",
    "rules, never added to the planted numbers: labels say what a reviewer found and the author fixed, so",
    "a false alarm here can be a problem nobody reported.",
)


def _percent(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.0%}"


def report(
    cases: Sequence[Case],
    runs: Sequence[CaseRun],
    label: str,
    *,
    input_price: float | None = None,
    output_price: float | None = None,
) -> str:
    """Planted and real cases in separate sections; real ones with fewer than two labellers on their own."""

    def section(part: Sequence[Case], level: str, kind: str) -> list[str]:
        return _section(score(part, runs), level, kind, input_price=input_price, output_price=output_price)

    planted = [c for c in cases if c.pull_request is None]
    final = [c for c in cases if c.pull_request is not None and not c.provisional]
    draft = [c for c in cases if c.provisional]
    lines = [f"# Evaluation: {label}"]
    if planted:
        lines += ["", *section(planted, "##", "planted")]
    if final:
        lines += ["", "## Real pull requests", "", *_REAL, "", *section(final, "###", "labelled")]
    if draft:
        lines += [
            "",
            "## Real pull requests: provisional labels",
            "",
            *_REAL,
            "",
            f"{len(draft)} cases, labelled by fewer than two people (a model's first pass counts as nobody).",
            "These numbers check the tooling, not the reviewer; quote none of them.",
            "",
            *section(draft, "###", "labelled"),
        ]
    return "\n".join(lines) + "\n"


def _section(
    score: Score,
    level: str,
    kind: str,
    *,
    input_price: float | None = None,
    output_price: float | None = None,
) -> list[str]:
    lines = [
        f"{score.cases} cases. Matching rules: docs/eval/README.md.",
        "",
        "False alarms count findings on clean pull requests and outside the code a case adds; remarks on",
        f"{kind} code that are not the {kind} defect are listed separately, not counted.",
        "",
        "| Category | Hits | False alarms | Misses | Precision | Recall |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    lines += [
        f"| {c.category} | {c.true_positives} | {c.false_positives} | {c.false_negatives} | "
        f"{_percent(c.precision)} | {_percent(c.recall)} |"
        for c in score.categories
    ]
    lines += [
        "",
        f"- Labelled defects found at the right place, any category: {score.located} of {score.labelled}.",
        f"- Clean pull requests with an inline comment (medium or above): {score.clean_with_inline} of "
        f"{score.clean_cases}.",
        f"- Model findings the validator dropped: {score.dropped} of {score.model_findings}.",
        f"- Duplicate findings: {score.duplicates}.",
        f"- Other remarks on {kind} code, not scored: {score.ignored} ({score.ignored_inline} at medium "
        "or above).",
        f"- Rule findings citing the right rule line: {score.citations_correct} of {score.citations_total}.",
        f"- Acceptance criteria judged correctly: {score.criteria_correct} of {score.criteria_total}.",
        f"- Scope creep found: {score.creep_found} of {score.creep_expected}, "
        f"with {score.creep_extra} extra.",
    ]
    if score.median_seconds is not None:
        p90 = f", {score.p90_seconds:.1f} s p90" if score.p90_seconds is not None else ""
        lines.append(f"- Latency: {score.median_seconds:.1f} s median{p90}.")
    if score.input_tokens is not None and score.output_tokens is not None:
        lines.append(
            f"- Tokens: {score.input_tokens:,} in, {score.output_tokens:,} out, over {score.usage_cases} "
            "reviewed cases."
        )
        if input_price is not None and output_price is not None and score.usage_cases:
            cost = (score.input_tokens * input_price + score.output_tokens * output_price) / 1_000_000
            lines.append(
                f"- Cost: ${cost / score.usage_cases:.2f} per pull request at the given prices. Approximate: "
                "cached input is priced as plain input, and failed attempts are not counted."
            )
    for title, items in (
        ("Errors", score.errors),
        ("Misses", score.misses),
        ("False alarms", score.false_alarms),
    ):
        if items:
            lines += ["", f"{level} {title}", "", *(f"- {item}" for item in items)]
    return lines
