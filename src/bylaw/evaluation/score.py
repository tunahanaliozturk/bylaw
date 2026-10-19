"""Compare saved runs with the case labels. The matching rules are listed in docs/eval/README.md."""

import statistics
from collections import Counter
from collections.abc import Sequence

from pydantic import BaseModel, ConfigDict

from bylaw.evaluation.cases import Case, ExpectedFinding, Span
from bylaw.evaluation.run import CaseRun
from bylaw.model import Category, Finding, ReviewResult, Severity

TOLERANCE = 2
_INLINE = frozenset({Severity.CRITICAL, Severity.HIGH, Severity.MEDIUM})


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class CategoryScore(_Frozen):
    category: Category
    true_positives: int
    false_positives: int
    false_negatives: int

    @property
    def precision(self) -> float | None:
        predicted = self.true_positives + self.false_positives
        return self.true_positives / predicted if predicted else None

    @property
    def recall(self) -> float | None:
        labelled = self.true_positives + self.false_negatives
        return self.true_positives / labelled if labelled else None


class Score(_Frozen):
    cases: int
    categories: tuple[CategoryScore, ...]
    labelled: int
    located: int
    # Findings on planted code that are neither the label nor a false alarm (allowed spans).
    ignored: int
    ignored_inline: int
    duplicates: int
    clean_cases: int
    clean_with_inline: int
    model_findings: int
    dropped: int
    # Rule findings that hit a label citing a rule line, and how many cited that same line.
    citations_total: int
    citations_correct: int
    # Hits on labels that name profile controls, and how many tagged at least one of them.
    controls_total: int = 0
    controls_correct: int = 0
    criteria_total: int
    criteria_correct: int
    creep_expected: int
    creep_found: int
    creep_extra: int
    median_seconds: float | None
    p90_seconds: float | None
    usage_cases: int
    input_tokens: int | None
    output_tokens: int | None
    errors: tuple[str, ...]
    misses: tuple[str, ...]
    false_alarms: tuple[str, ...]


def _near_label(finding: Finding, label: ExpectedFinding) -> bool:
    return _near(finding, label) or any(_near(finding, span) for span in label.also)


def _near(finding: Finding, span: Span) -> bool:
    start, end = span.lines
    return (
        finding.file == span.file
        and finding.line_start <= end + TOLERANCE
        and finding.line_end >= start - TOLERANCE
    )


def score(cases: Sequence[Case], runs: Sequence[CaseRun]) -> Score:  # noqa: PLR0912, PLR0915 - one pass, many counters
    ids = {case.id for case in cases}
    # Only the scored cases: a runs directory can hold a whole run while --only scores part of it.
    runs = [run for run in runs if run.case_id in ids]
    by_id = {run.case_id: run for run in runs}
    tp: Counter[Category] = Counter()
    fp: Counter[Category] = Counter()
    fn: Counter[Category] = Counter()
    located = duplicates = clean_cases = clean_with_inline = ignored = ignored_inline = 0
    criteria_total = criteria_correct = creep_expected = creep_found = creep_extra = 0
    citations_total = citations_correct = controls_total = controls_correct = 0
    errors: list[str] = []
    misses: list[str] = []
    false_alarms: list[str] = []
    for case in cases:
        run = by_id.get(case.id)
        if run is None:
            errors.append(f"{case.id}: no run")
            result = ReviewResult()
        else:
            if run.error is not None:
                errors.append(f"{case.id}: {run.error}")
            result = run.result
        open_labels = list(case.findings)
        matched: list[ExpectedFinding] = []
        # Labels are tracked by position: two labels can be equal values.
        near_label: set[int] = set()
        inline = False
        # Right-category findings first, so the order a reviewer lists findings in never changes the score.
        ordered = sorted(
            result.findings,
            key=lambda f: not any(_near_label(f, e) and f.category in e.categories for e in case.findings),
        )
        for finding in ordered:
            near_label.update(i for i, label in enumerate(case.findings) if _near_label(finding, label))
            hit = next(
                (e for e in open_labels if _near_label(finding, e) and finding.category in e.categories), None
            )
            if hit is not None:
                open_labels.remove(hit)
                matched.append(hit)
                tp[finding.category] += 1
                if finding.category == Category.RULE and hit.evidence:
                    citations_total += 1
                    citations_correct += finding.evidence == hit.evidence
                if hit.controls:
                    controls_total += 1
                    controls_correct += not set(finding.controls).isdisjoint(hit.controls)
                continue
            if any(_near_label(finding, e) for e in matched):
                duplicates += 1
                continue
            if any(_near_label(finding, e) for e in open_labels):
                # The defect, found at its place under another category: located, missed, not invented.
                continue
            if any(_near(finding, span) for span in case.allowed):
                ignored += 1
                ignored_inline += finding.severity in _INLINE
                continue
            fp[finding.category] += 1
            false_alarms.append(
                f"{case.id}: {finding.file}:{finding.line_start} {finding.category} {finding.message[:80]}"
            )
            inline = inline or finding.severity in _INLINE
        located += len(near_label)
        for label in open_labels:
            fn[label.categories[0]] += 1
            misses.append(f"{case.id}: {label.note}")
        if case.kind == "clean":
            clean_cases += 1
            clean_with_inline += inline
        statuses = {c.criterion: c.status for c in result.criteria}
        for key, accepted in case.criteria.items():
            criteria_total += 1
            criteria_correct += statuses.get(key) in accepted
        open_creep = list(case.scope_creep)
        creep_expected += len(open_creep)
        for creep in result.scope_creep:
            hit_creep = next(
                (c for c in open_creep if c.file == creep.file and abs(c.line - creep.line) <= TOLERANCE),
                None,
            )
            if hit_creep is None:
                creep_extra += 1
            else:
                open_creep.remove(hit_creep)
                creep_found += 1
    seconds = sorted(r.seconds for r in runs if r.seconds is not None and r.error is None)
    tokens_in = [r.input_tokens for r in runs if r.input_tokens is not None]
    tokens_out = [r.output_tokens for r in runs if r.output_tokens is not None]
    return Score(
        cases=len(cases),
        categories=tuple(
            CategoryScore(category=c, true_positives=tp[c], false_positives=fp[c], false_negatives=fn[c])
            for c in Category
        ),
        labelled=sum(len(c.findings) for c in cases),
        located=located,
        ignored=ignored,
        ignored_inline=ignored_inline,
        duplicates=duplicates,
        clean_cases=clean_cases,
        clean_with_inline=clean_with_inline,
        model_findings=sum(r.model_findings for r in runs),
        dropped=sum(r.dropped_findings for r in runs),
        citations_total=citations_total,
        citations_correct=citations_correct,
        controls_total=controls_total,
        controls_correct=controls_correct,
        criteria_total=criteria_total,
        criteria_correct=criteria_correct,
        creep_expected=creep_expected,
        creep_found=creep_found,
        creep_extra=creep_extra,
        median_seconds=statistics.median(seconds) if seconds else None,
        p90_seconds=statistics.quantiles(seconds, n=10, method="inclusive")[-1] if seconds[1:] else None,
        usage_cases=len(tokens_in),
        input_tokens=sum(tokens_in) if tokens_in else None,
        output_tokens=sum(tokens_out) if tokens_out else None,
        errors=tuple(errors),
        misses=tuple(misses),
        false_alarms=tuple(false_alarms),
    )
