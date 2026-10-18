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


@pytest.mark.parametrize(
    "status",
    [
        "Status: Superseded by [ADR 0005](0005-x.md)",
        "Status: Accepted, superseded by 0012",
        "Status: Deprecated",
        "Status: Rejected",
        "Status: Proposed",
        "---\nstatus: proposed\n---",
        "## Status\n\nAccepted\n\nSuperseded by [5. Use Postgres](0005-use-postgres.md)",
    ],
    ids=[
        "superseded",
        "accepted-then-superseded",
        "deprecated",
        "rejected",
        "proposed",
        "madr-proposed",
        "adr-tools",
    ],
)
def test_superseded_deprecated_rejected_and_proposed_adrs_are_left_out(status: str) -> None:
    markdown = f"# 3. Old way\n\n{status}\n\n## Decision\n\nDo it the old way.\n"
    source = FakeSource(base={"docs/adr/0003-old.md": markdown})

    decisions, _ = collect_decisions(source, GLOBS)

    assert decisions == ()


def test_an_adr_that_supersedes_another_is_still_in_force() -> None:
    markdown = "# 5. New way\n\nStatus: Accepted. Supersedes 0003.\n\n## Decision\n\nDo it the new way.\n"
    source = FakeSource(base={"docs/adr/0005-new.md": markdown})

    (decision,), _ = collect_decisions(source, GLOBS)

    assert decision.status == "Accepted. Supersedes 0003."


def test_headings_inside_code_fences_are_not_sections() -> None:
    markdown = (
        "# 4. Deploy\n\n```md\n# Not the title\n## Status\nRejected\n```\n\nStatus: Accepted\n\n"
        "## Decision\n\nRun the script first:\n\n```sh\n# setup\n./setup.sh\n```\n\n"
        "~~~\n## Consequences\n~~~\n\n"
        "Never deploy by hand.\n\n## Consequences\n\nSlower.\n"
    )
    source = FakeSource(base={"docs/adr/0004-deploy.md": markdown})

    (decision,), _ = collect_decisions(source, GLOBS)

    assert decision.title == "4. Deploy"
    assert decision.text.splitlines()[-1] == "Never deploy by hand."
    assert (
        markdown.splitlines()[decision.start - 1 + len(decision.text.splitlines()) - 1]
        == "Never deploy by hand."
    )


def test_the_title_skips_front_matter_and_falls_back_to_its_title_key() -> None:
    template = (
        "---\n# These are optional elements. Feel free to remove any of them.\nstatus: accepted\n"
        "title: Use MADR\n---\n\n## Context\n\nWe need a format.\n\n## Decision Outcome\n\nMADR.\n"
    )
    with_h1 = template.replace("## Context", "# Use MADR 4\n\n## Context")
    source = FakeSource(base={"docs/adr/0001-madr.md": template, "docs/adr/0002-madr.md": with_h1})

    decisions, _ = collect_decisions(source, GLOBS)

    assert [d.title for d in decisions] == ["Use MADR 4", "Use MADR"]


def test_numbered_bold_and_setext_headings_are_recognised() -> None:
    numbered = "Use X\n=====\n\n## **Status**\n\nAccepted\n\n## 3. Decision\n\nWe use X.\n"
    setext = (
        "# Use Y\n\nStatus: Accepted\n\nDecision\n--------\n\nWe use Y.\n\n"
        "Consequences\n------------\n\nNone.\n"
    )
    source = FakeSource(base={"docs/adr/0001-x.md": numbered, "docs/adr/0002-y.md": setext})

    y, x = collect_decisions(source, GLOBS)[0]

    assert (x.title, x.start, x.text) == ("Use X", 8, "## 3. Decision\n\nWe use X.")
    assert (y.title, y.start, y.text) == ("Use Y", 5, "Decision\n--------\n\nWe use Y.")


def test_lines_are_numbered_as_github_numbers_them() -> None:
    markdown = (
        "# T\r\n\r\nStatus: Accepted\r\n\r\n## Decision\r\n\r\nUse a\u2028b and c\x0cd.\r\nSecond rule.\r\n"
    )
    source = FakeSource(base={"docs/adr/0001-t.md": markdown})

    (decision,), _ = collect_decisions(source, GLOBS)

    assert decision.start == 5
    assert decision.text == "## Decision\n\nUse a\u2028b and c\x0cd.\nSecond rule."
