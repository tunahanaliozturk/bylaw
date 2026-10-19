"""The per-repository report: what bylaw found across closed pull requests and what happened to it.

Built from the records on the outcome branch (ADR 0022). `report_data` counts; `render_report` writes a
static page with light and dark PNG charts, no JavaScript.
"""

from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass

from bylaw.learn import Record, tally
from bylaw.model import Category

_MONTHS = 12
_TOP_RULES = 10


@dataclass(frozen=True, slots=True)
class CategoryRow:
    category: str
    fixed: int = 0
    muted: int = 0
    resolved: int = 0
    suppressed: int = 0
    # Still there when the pull request closed: nobody fixed, muted or resolved it.
    open: int = 0

    @property
    def total(self) -> int:
        return self.fixed + self.muted + self.resolved + self.suppressed + self.open

    @property
    def fix_rate(self) -> float | None:
        return self.fixed / self.total if self.total else None


@dataclass(frozen=True, slots=True)
class MonthRow:
    month: str
    pulls: int
    met: int
    partial: int
    missing: int
    not_assessed: int


@dataclass(frozen=True, slots=True)
class RuleRow:
    category: str
    rule: str
    # Pull requests in which maintainers muted or resolved it without a change, and in which it was fixed.
    pull_requests: int
    fixed: int


@dataclass(frozen=True, slots=True)
class ReportData:
    repository: str
    pulls: int
    merged: int
    # The first and last day a recorded pull request closed.
    first: str | None
    last: str | None
    categories: tuple[CategoryRow, ...]
    months: tuple[MonthRow, ...]
    dismissed: tuple[RuleRow, ...]


def report_data(repository: str, records: Iterable[Record]) -> ReportData:
    records = list(records)
    counts = Counter((f.category, f.outcome) for r in records for f in r.findings)
    categories = tuple(
        CategoryRow(
            category=c.value,
            fixed=counts[c.value, "fixed"],
            muted=counts[c.value, "muted"],
            resolved=counts[c.value, "resolved"],
            suppressed=counts[c.value, "suppressed"],
            open=counts[c.value, "open"],
        )
        for c in Category
    )
    months: dict[str, Counter[str]] = {}
    for record in records:
        if record.closed_at:
            month = months.setdefault(record.closed_at[:7], Counter())
            month.update(record.criteria)
            month["pulls"] += 1
    dated = sorted(r.closed_at[:10] for r in records if r.closed_at)
    dismissed = sorted(
        (
            RuleRow(category=category, rule=rule, pull_requests=len(by_pull), fixed=fixes)
            for (category, rule), (by_pull, fixes) in tally(records).items()
        ),
        key=lambda row: (-row.pull_requests, row.rule),
    )
    return ReportData(
        repository=repository,
        pulls=len(records),
        merged=sum(r.merged for r in records),
        first=dated[0] if dated else None,
        last=dated[-1] if dated else None,
        categories=categories,
        months=tuple(
            MonthRow(
                month=month,
                pulls=c["pulls"],
                met=c["met"],
                partial=c["partial"],
                missing=c["missing"],
                not_assessed=c["not assessed"],
            )
            for month, c in sorted(months.items())[-_MONTHS:]
        ),
        dismissed=tuple(dismissed[:_TOP_RULES]),
    )
