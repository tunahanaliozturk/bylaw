import pytest

from bylaw.decisions import (
    DECISION_CHARS,
    DECISIONS_CHARS,
    MAX_ADR_FILES,
    accepted,
    collect_decisions,
    is_adr,
    status_of,
)
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


def _adr(status: str) -> str:
    return f"# 7. Retry\n\n{status}\n\n## Decision\n\nRetry twice.\n"


@pytest.mark.parametrize(
    "status",
    [
        "## Status\n\nAccepted\n\nSupersedes [3. Keep the deprecated logger](0003-deprecated-logger.md)",
        "## Status\n\nAccepted\n\nAmends [4. Retry rejected payments](0004-retry-rejected-payments.md)",
        "## Status\n\nAccepted. The old approach is now obsolete.",
        "Status: Accepted, see [the rejected options](#options)",
    ],
    ids=["adr-tools-supersedes", "adr-tools-amends", "prose", "link-text"],
)
def test_links_and_prose_in_a_status_do_not_retire_an_accepted_adr(status: str) -> None:
    source = FakeSource(base={"docs/adr/0007-retry.md": _adr(status)})

    (decision,), _ = collect_decisions(source, GLOBS)

    assert decision.status.startswith("Accepted")


@pytest.mark.parametrize("status", ["Status: Not accepted", "Status: not yet approved", "Status: Declined"])
def test_a_negated_or_declined_status_is_not_in_force(status: str) -> None:
    assert collect_decisions(FakeSource(base={"docs/adr/0007-retry.md": _adr(status)}), GLOBS)[0] == ()


@pytest.mark.parametrize(
    "status",
    [
        "Status: Implemented",
        "Status: Adopted",
        "## Status\n\nDecided",
        "| Field | Value |\n| --- | --- |\n| Status | Accepted |",
    ],
    ids=["implemented", "adopted", "decided", "table"],
)
def test_implemented_adopted_decided_and_table_statuses_are_in_force(status: str) -> None:
    (decision,), _ = collect_decisions(FakeSource(base={"docs/adr/0007-retry.md": _adr(status)}), GLOBS)

    assert decision.path == "docs/adr/0007-retry.md"


def test_a_status_history_counts_its_last_entry_and_the_brief_shows_it() -> None:
    accepted_last = _adr("## Status\n\n- 2023-01-01 proposed\n- 2023-02-01 accepted")
    retired_last = _adr("## Status\n\n- 2023-01-01 accepted\n- 2024-05-01 superseded by [ADR 9](0009-x.md)")
    source = FakeSource(base={"docs/adr/0007-retry.md": accepted_last, "docs/adr/0008-old.md": retired_last})

    (decision,), _ = collect_decisions(source, GLOBS)

    assert (decision.path, decision.status) == ("docs/adr/0007-retry.md", "2023-02-01 accepted")


def test_adrs_in_subdirectories_and_under_wildcard_directories_are_found() -> None:
    source = FakeSource(
        base={
            "docs/adr/backend/0003-queue.md": _adr("Status: Accepted"),
            "services/pay/docs/adr/0001-money.md": _adr("Status: Accepted"),
        }
    )

    decisions, _ = collect_decisions(
        source, ("docs/adr/**", "services/*/docs/adr/*.md"), changed=["services/pay/app.py"]
    )

    assert {d.path for d in decisions} == {
        "docs/adr/backend/0003-queue.md",
        "services/pay/docs/adr/0001-money.md",
    }


def test_readme_index_and_template_files_are_not_adrs_and_do_not_count_toward_the_cap() -> None:
    base = {f"docs/adr/{n:04}-d.md": _adr("Status: Accepted") for n in range(1, MAX_ADR_FILES + 1)}
    for name in ("README.md", "index.md", "template.md", "0000-adr-template.md"):
        base[f"docs/adr/{name}"] = _adr("Status: Accepted")

    decisions, notes = collect_decisions(FakeSource(base=base), GLOBS)

    assert len(decisions) == MAX_ADR_FILES
    assert not any("newest" in note for note in notes)
    assert not is_adr("docs/adr/README.md", GLOBS)
    assert not is_adr("docs/adr/0000-adr-template.md", GLOBS)


def test_adr_texts_are_read_in_one_batch() -> None:
    source = FakeSource(base={f"docs/adr/{n:04}-d.md": _adr("Status: Accepted") for n in range(1, 4)})

    collect_decisions(source, GLOBS)

    assert source.batch_reads == [["docs/adr/0003-d.md", "docs/adr/0002-d.md", "docs/adr/0001-d.md"]]


def test_a_package_adr_applies_only_under_its_package_and_is_read_only_when_the_package_changed() -> None:
    source = FakeSource(
        base={
            "docs/adr/0001-root.md": _adr("Status: Accepted"),
            "packages/api/docs/adr/0002-api.md": _adr("Status: Accepted"),
            "packages/worker/adr/0003-worker.md": _adr("Status: Accepted"),
        }
    )

    decisions, _ = collect_decisions(source, ("**/adr/**",), changed=["packages/api/handlers.py"])

    assert [(d.path, d.directory) for d in decisions] == [
        ("packages/api/docs/adr/0002-api.md", "packages/api"),
        ("docs/adr/0001-root.md", ""),
    ]


def test_adrs_bylaw_cannot_read_are_named_in_one_note_with_the_reason() -> None:
    source = FakeSource(
        base={
            "docs/adr/0001-none.md": "# 1. None\n\n## Decision\n\nX.\n",
            "docs/adr/0002-odd.md": _adr("Status: Ratified"),
            "docs/adr/0003-prose.md": "# 3. Prose\n\nStatus: Accepted\n\nWe do X.\n",
            "docs/adr/0004-proposal.md": _adr("Status: Proposed"),
            "docs/adr/0005-old.md": _adr("Status: Superseded by 0006"),
        }
    )

    decisions, notes = collect_decisions(source, GLOBS)

    assert decisions == ()
    assert notes == (
        "These ADRs were left out because bylaw could not read them: docs/adr/0003-prose.md (no Decision "
        'section), docs/adr/0002-odd.md (status "Ratified" not recognised), '
        "docs/adr/0001-none.md (no status).",
    )
