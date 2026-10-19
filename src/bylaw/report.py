"""The per-repository report: what bylaw found across closed pull requests and what happened to it.

Built from the records on the outcome branch (ADR 0022). `report_data` counts; `render_report` writes a
static page with light and dark PNG charts, no JavaScript.
"""

from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from html import escape

from bylaw.charts import THEMES, stacked_bars
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


_FINDING_SERIES = ("fixed", "muted", "resolved", "suppressed", "open at close")
_CRITERIA_SERIES = ("met", "partial", "missing", "not assessed")
_STYLE = """
:root { --bg: #ffffff; --fg: #1f2328; --soft: #59636e; --line: #d1d9e0; }
@media (prefers-color-scheme: dark) {
  :root { --bg: #0d1117; --fg: #e6edf3; --soft: #9198a1; --line: #3d444d; }
}
body { margin: 0 auto; max-width: 760px; padding: 32px 16px; background: var(--bg); color: var(--fg);
  font: 15px/1.5 system-ui, -apple-system, "Segoe UI", sans-serif; }
h1 { font-size: 24px; margin: 0 0 4px; }
h2 { font-size: 18px; margin: 40px 0 12px; }
.soft { color: var(--soft); }
img { display: block; max-width: 100%; height: auto; }
.table { overflow-x: auto; }
table { border-collapse: collapse; width: 100%; margin-top: 12px; font-variant-numeric: tabular-nums; }
th, td { text-align: right; padding: 6px 8px; border-bottom: 1px solid var(--line); white-space: nowrap; }
th:first-child, td:first-child { text-align: left; }
code { font-size: 13px; }
""".strip()


def render_report(data: ReportData, generated: str) -> dict[str, bytes]:
    """The report's files: `index.html` and the chart PNGs it shows, light and dark."""
    files: dict[str, bytes] = {}
    finding_rows = [
        (row.category, (row.fixed, row.muted, row.resolved, row.suppressed, row.open))
        for row in data.categories
    ]
    _chart(files, "findings", finding_rows, _FINDING_SERIES)
    month_rows = [(m.month, (m.met, m.partial, m.missing, m.not_assessed)) for m in data.months]
    if month_rows:
        _chart(files, "criteria", month_rows, _CRITERIA_SERIES)
    sections = [
        "<h1>bylaw report</h1>",
        f'<p class="soft">{_lede(data)} Made on {escape(generated)}.</p>',
        "<h2>Findings and what happened to them</h2>",
        _picture("findings", "Findings by category and outcome", finding_rows, _FINDING_SERIES),
        _table(
            ["Category", "Found", "Fixed", "Muted", "Resolved", "Suppressed", "Open at close", "Fix rate"],
            [
                [
                    row.category,
                    row.total,
                    row.fixed,
                    row.muted,
                    row.resolved,
                    row.suppressed,
                    row.open,
                    _rate(row),
                ]
                for row in data.categories
            ],
        ),
        '<p class="soft">Fixed: gone on a later run in which the model read its file. Muted: a maintainer '
        "replied <code>bylaw: ignore</code>. Resolved: someone other than the author resolved its thread "
        "with the finding still there. Suppressed: hidden by a <code>[[suppress]]</code> entry. Open at "
        "close: none of these when the pull request closed.</p>",
        "<h2>Criteria per month</h2>",
        *(
            [
                _picture("criteria", "Acceptance criteria per month by status", month_rows, _CRITERIA_SERIES),
                _table(
                    ["Month", "Pull requests", "Met", "Partial", "Missing", "Not assessed"],
                    [[m.month, m.pulls, m.met, m.partial, m.missing, m.not_assessed] for m in data.months],
                ),
                '<p class="soft">As the last review of each pull request judged them, by the month it '
                "closed.</p>",
            ]
            if month_rows
            else ['<p class="soft">No criteria have been recorded yet.</p>']
        ),
        "<h2>Rules dismissed most</h2>",
        _table(
            ["Rule", "Category", "Dismissed in", "Fixed in"],
            [
                [f"<code>{escape(r.rule)}</code>", r.category, r.pull_requests, r.fixed]
                for r in data.dismissed
            ],
            raw_first=True,
        )
        if data.dismissed
        else '<p class="soft">No rule has been muted or resolved without a change yet.</p>',
        '<p class="soft">Counted in pull requests, as suggestions count them: a dismissal by a pull '
        "request's own author never counts. A rule dismissed often may deserve a suppression or a clearer "
        "wording; bylaw suggests one when <code>[learn]</code> allows it.</p>",
    ]
    page = (
        '<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        '<meta name="color-scheme" content="light dark">\n'
        f"<title>bylaw report for {escape(data.repository)}</title>\n<style>\n{_STYLE}\n</style>\n</head>\n"
        "<body>\n" + "\n".join(sections) + "\n</body>\n</html>\n"
    )
    files["index.html"] = page.encode("utf-8")
    return files


def _lede(data: ReportData) -> str:
    repository = f"<code>{escape(data.repository)}</code>"
    if not data.pulls:
        return f"No pull request has been recorded yet for {repository}. Records start once learning is on."
    when = f" between {data.first} and {data.last}" if data.first else ""
    return f"{repository}: {data.pulls} pull requests closed{when}, {data.merged} of them merged."


def _chart(
    files: dict[str, bytes], name: str, rows: Sequence[tuple[str, Sequence[int]]], series: tuple[str, ...]
) -> None:
    for theme in THEMES:
        files[f"{name}-{theme}.png"] = stacked_bars(rows, series, theme)


def _picture(
    name: str, title: str, rows: Sequence[tuple[str, Sequence[int]]], series: tuple[str, ...]
) -> str:
    # The table below has the same numbers; the alternative text says what the chart shows.
    described = "; ".join(
        f"{label}: " + ", ".join(f"{value} {part}" for value, part in zip(values, series, strict=True))
        for label, values in rows
    )
    return (
        f'<picture><source srcset="{name}-dark.png" media="(prefers-color-scheme: dark)">'
        f'<img src="{name}-light.png" alt="{escape(title)}. {escape(described)}."></picture>'
    )


def _table(head: list[str], rows: list[list[object]], *, raw_first: bool = False) -> str:
    """A table; cells are escaped, except a first cell the caller already wrote as markup."""
    lines = ["<tr>" + "".join(f"<th>{escape(h)}</th>" for h in head) + "</tr>"]
    for row in rows:
        cells = [str(c) if raw_first and i == 0 else escape(str(c)) for i, c in enumerate(row)]
        lines.append("<tr>" + "".join(f"<td>{cell}</td>" for cell in cells) + "</tr>")
    return '<div class="table"><table>\n' + "\n".join(lines) + "\n</table></div>"


def _rate(row: CategoryRow) -> str:
    return "-" if row.fix_rate is None else f"{round(row.fix_rate * 100)}%"
