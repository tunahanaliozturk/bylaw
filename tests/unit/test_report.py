"""RPT-1 and RPT-2: the per-repository report, from the outcome store's records (ADR 0022)."""

from bylaw.learn import Record, StoredFinding
from bylaw.plan import OutcomeStatus
from bylaw.report import report_data


def _finding(
    n: int, outcome: OutcomeStatus, category: str = "rule", rule: str | None = "ruff:S101"
) -> StoredFinding:
    by = "maintainer" if outcome in ("muted", "resolved") else None
    return StoredFinding(
        fingerprint=f"{n:016x}", category=category, rule=rule, file="a.py", outcome=outcome, by=by
    )


def _record(
    number: int, *findings: StoredFinding, closed_at: str | None = "2027-08-02T10:00:00Z", **criteria: int
) -> Record:
    return Record(
        pull_request=number,
        author="author",
        merged=number % 2 == 0,
        closed_at=closed_at,
        head_sha="h",
        findings=findings,
        criteria=criteria,
    )


def test_findings_are_counted_by_category_and_what_happened_to_them() -> None:
    records = [
        _record(1, _finding(1, "fixed"), _finding(2, "muted"), _finding(3, "open", "security", None)),
        _record(2, _finding(4, "fixed"), _finding(5, "suppressed"), _finding(6, "resolved", "bug", None)),
    ]

    data = report_data("acme/app", records)

    rows = {row.category: row for row in data.categories}
    assert [row.category for row in data.categories] == ["security", "bug", "rule", "requirement"]
    assert (rows["rule"].fixed, rows["rule"].muted, rows["rule"].suppressed, rows["rule"].total) == (
        2,
        1,
        1,
        4,
    )
    assert (rows["security"].open, rows["bug"].resolved, rows["requirement"].total) == (1, 1, 0)
    assert rows["rule"].fix_rate == 0.5
    assert (data.pulls, data.merged) == (2, 1)


def test_criteria_are_summed_per_month_in_order_and_the_last_twelve_kept() -> None:
    records = [
        _record(n, closed_at=f"{2026 + (n - 1) // 12}-{(n - 1) % 12 + 1:02}-15T00:00:00Z", met=n, missing=1)
        for n in range(1, 15)
    ]
    records.append(_record(15, closed_at="2027-02-20T00:00:00Z", met=1, partial=2))
    records.append(_record(16, closed_at=None, met=100))

    months = report_data("acme/app", records).months

    assert [m.month for m in months] == [f"2026-{m:02}" for m in range(3, 13)] + ["2027-01", "2027-02"]
    assert (months[-1].pulls, months[-1].met, months[-1].partial, months[-1].missing) == (2, 15, 2, 1)


def test_the_rules_dismissed_most_count_pull_requests_and_never_the_author_s_own_dismissals() -> None:
    own = StoredFinding(
        fingerprint="x", category="rule", rule="CONTRIBUTING.md:4", file="a.py", outcome="muted", by="author"
    )
    records = [
        _record(1, _finding(1, "muted"), own),
        _record(2, _finding(2, "resolved"), _finding(3, "muted")),
        _record(3, _finding(4, "fixed")),
    ]

    (top,) = report_data("acme/app", records).dismissed

    assert (top.rule, top.pull_requests, top.fixed) == ("ruff:S101", 2, 1)


def test_a_store_with_no_records_gives_an_empty_report() -> None:
    data = report_data("acme/app", [])

    assert (data.pulls, data.months, data.dismissed, data.first, data.last) == (0, (), (), None, None)
    assert all(row.total == 0 and row.fix_rate is None for row in data.categories)
