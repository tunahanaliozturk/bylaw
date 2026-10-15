"""The Markdown report README numbers are quoted from."""

from bylaw.evaluation.score import Score


def _percent(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.0%}"


def render(
    score: Score, label: str, *, input_price: float | None = None, output_price: float | None = None
) -> str:
    lines = [
        f"# Evaluation: {label}",
        "",
        f"{score.cases} cases. Matching rules: docs/eval/README.md.",
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
        f"- Acceptance criteria judged correctly: {score.criteria_correct} of {score.criteria_total}.",
        f"- Scope creep found: {score.creep_found} of {score.creep_expected}, "
        f"with {score.creep_extra} extra.",
    ]
    if score.median_seconds is not None:
        p90 = f", {score.p90_seconds:.1f} s p90" if score.p90_seconds is not None else ""
        lines.append(f"- Latency: {score.median_seconds:.1f} s median{p90}.")
    if score.input_tokens is not None and score.output_tokens is not None:
        lines.append(f"- Tokens: {score.input_tokens:,} in, {score.output_tokens:,} out.")
        if input_price is not None and output_price is not None and score.cases:
            cost = (score.input_tokens * input_price + score.output_tokens * output_price) / 1_000_000
            lines.append(
                f"- Cost: ${cost / score.cases:.2f} per pull request at the given prices, an upper bound "
                "because cached input is billed as full input."
            )
    for title, items in (
        ("Errors", score.errors),
        ("Misses", score.misses),
        ("False alarms", score.false_alarms),
    ):
        if items:
            lines += ["", f"## {title}", "", *(f"- {item}" for item in items)]
    return "\n".join(lines) + "\n"
