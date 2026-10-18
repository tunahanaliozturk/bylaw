import pytest

from bylaw.decisions import DECISION_CHARS, DECISIONS_CHARS, accepted, collect_decisions, status_of
from tests.unit.fakes import FakeSource

GLOBS = ("docs/adr/**", "docs/decisions/**")

NYGARD = """# 2. Use SQLite

## Status

Accepted

## Context

We need storage.

## Decision

We store everything in SQLite.

## Consequences

One file to back up.
"""


@pytest.mark.parametrize(
    "markdown",
    [
        "# 0004: Rules\n\nStatus: Accepted, 2026-10-15. Amended by 0014.\n\n## Context\n",
        "# Rules\n\n**Status:** accepted\n",
        "# Rules\n\n* Status: ACCEPTED\n* Date: 2026-01-02\n",
        "---\nstatus: accepted\ndate: 2026-01-02\n---\n\n# Rules\n",
        NYGARD,
        "# Rules\n\n## status\n\n- Approved by the architecture group\n",
    ],
    ids=["status-line", "bold-line", "madr-bullets", "madr-front-matter", "nygard-section", "approved"],
)
def test_the_status_of_an_adr_is_read_from_a_line_a_section_or_front_matter_in_any_case(
    markdown: str,
) -> None:
    status = status_of(markdown)

    assert status is not None
    assert accepted(status)


def test_a_status_mentioned_in_the_body_is_not_the_adr_status() -> None:
    markdown = "# Errors\n\n## Context\n\nStatus: accepted is what the API answers.\n"

    assert status_of(markdown) is None


def test_an_adr_without_an_accepted_status_is_not_accepted() -> None:
    assert not accepted("Proposed")
    assert not accepted("Draft, 2026-10-01")


def test_accepted_adrs_are_collected_from_the_base_branch_newest_first() -> None:
    older = "# 1. Use JSON\n\nStatus: Accepted\n\n## Decision\n\nJSON files.\n"
    source = FakeSource(
        base={
            "docs/adr/0001-json.md": older,
            "docs/adr/0002-sqlite.md": NYGARD,
            "docs/adr/README.md": "# Decisions\n\nAn index.\n",
            "docs/adr/diagram.png": "binary",
            "docs/other/0003-not-an-adr.md": "# 3\n\nStatus: Accepted\n\n## Decision\n\nNo.\n",
        },
        head={"docs/adr/0002-sqlite.md": NYGARD.replace("SQLite.", "Postgres.")},
    )

    decisions, notes = collect_decisions(source, GLOBS)

    assert [(d.path, d.title, d.status) for d in decisions] == [
        ("docs/adr/0002-sqlite.md", "2. Use SQLite", "Accepted"),
        ("docs/adr/0001-json.md", "1. Use JSON", "Accepted"),
    ]
    sqlite = decisions[0]
    assert sqlite.start == 11
    assert sqlite.text == "## Decision\n\nWe store everything in SQLite."
    assert notes == ()


def test_madr_decision_outcome_is_the_decision_and_its_drivers_are_not() -> None:
    markdown = (
        "---\nstatus: accepted\n---\n# Use MADR\n\n## Decision Drivers\n\n* speed\n\n"
        "## Decision Outcome\n\nChosen option: MADR.\n\n### Consequences\n\n* Good.\n\n## More\n"
    )
    source = FakeSource(base={"docs/decisions/0001-madr.md": markdown})

    (decision,), _ = collect_decisions(source, GLOBS)

    assert decision.title == "Use MADR"
    assert decision.start == 10
    assert decision.text == "## Decision Outcome\n\nChosen option: MADR.\n\n### Consequences\n\n* Good."


def test_an_accepted_adr_without_a_decision_section_is_left_out() -> None:
    source = FakeSource(base={"docs/adr/0001-x.md": "# X\n\nStatus: Accepted\n\nWe do X.\n"})

    decisions, _ = collect_decisions(source, GLOBS)

    assert decisions == ()


def test_a_long_decision_is_cut_on_its_own_lines_and_noted() -> None:
    paragraph = "We keep one paragraph on a single line, " * 80
    markdown = f"# Long\n\nStatus: Accepted\n\n## Decision\n\nShort first line.\n{paragraph}\n\nMore.\n"
    source = FakeSource(base={"docs/adr/0001-long.md": markdown})

    (decision,), notes = collect_decisions(source, GLOBS)

    assert decision.cut
    assert len(decision.text) <= DECISION_CHARS
    shown = decision.text.splitlines()
    assert shown[:3] == ["## Decision", "", "Short first line."]
    assert paragraph.startswith(shown[3])
    assert any("docs/adr/0001-long.md" in note and "start" in note for note in notes)


def test_older_decisions_beyond_the_total_budget_are_left_out_and_named() -> None:
    base = {
        f"docs/adr/{n:04}-d.md": f"# D{n}\n\nStatus: Accepted\n\n## Decision\n\n{'x' * 1500}\n"
        for n in range(1, 13)
    }

    decisions, notes = collect_decisions(FakeSource(base=base), GLOBS)

    assert sum(len(d.text) for d in decisions) <= DECISIONS_CHARS
    shown = [d.path for d in decisions]
    assert shown == sorted(shown, reverse=True)
    assert shown[0] == "docs/adr/0012-d.md"
    left_out = sorted(set(base) - set(shown))
    assert left_out and max(left_out) < min(shown)
    assert any("docs/adr/0001-d.md" in note and "left out" in note for note in notes)
