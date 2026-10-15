from bylaw.model import ChangedFile
from bylaw.requirements import collect_requirements, extract_criteria, parse_issue_refs, spec_paths
from bylaw.source import Issue, IssueRef
from tests.unit.fakes import FakeSource

GLOBS = ("docs/specs/**", "docs/adr/**", "**/REQUIREMENTS.md")


def test_closing_keywords_in_every_form_become_issue_refs() -> None:
    texts = [
        "Closes #12 and fixes Octo/Lib#3.",
        "Resolves: #5",
        "Fixes https://github.com/octo/app/issues/9",
        "Mentions #77 without a keyword.",
        "Closes #12 again.",
    ]

    refs = parse_issue_refs(texts, "octo/app")

    assert refs == (
        IssueRef("octo", "app", 12),
        IssueRef("octo", "lib", 3),
        IssueRef("octo", "app", 5),
        IssueRef("octo", "app", 9),
    )


def test_a_bare_reference_needs_a_default_repository() -> None:
    assert parse_issue_refs(["Closes #12", "Fixes octo/lib#3"], None) == (IssueRef("octo", "lib", 3),)


def test_spec_paths_come_from_changed_specs_and_safe_links() -> None:
    changed = [
        ChangedFile(path="docs/specs/login.md", status="added"),
        ChangedFile(path="docs/specs/old.md", status="removed"),
        ChangedFile(path="src/app.py", status="modified"),
        ChangedFile(path="svc/REQUIREMENTS.md", status="modified"),
    ]
    body = (
        "See [spec](./docs/specs/session.md#tokens), [escape](../../secret.md), "
        "[web](https://example.com/a.md), "
        "https://github.com/octo/app/blob/main/docs/adr/0001-x.md and "
        "https://github.com/other/repo/blob/main/docs/specs/theirs.md"
    )

    paths = spec_paths(changed, body, GLOBS, "octo/app")

    assert paths == (
        "docs/specs/login.md",
        "svc/REQUIREMENTS.md",
        "docs/adr/0001-x.md",
        "docs/specs/session.md",
    )


def test_criteria_come_from_task_lists_criteria_sections_and_gherkin() -> None:
    markdown = "\n".join(
        [
            "# Login",
            "Intro text.",
            "- [ ] Users can sign in with email",
            "## Acceptance criteria",
            "1. Wrong password shows an error",
            "- Locked accounts cannot sign in",
            "### Detail",
            "- Error text is translated",
            "## Notes",
            "- Not a criterion",
            "```",
            "- [ ] inside a code fence",
            "```",
            "Given a signed in user",
            "When the session expires",
            "Then they are asked to sign in again",
            "",
            "- [x] Users can sign in with email",
        ]
    )

    criteria = extract_criteria(markdown)

    assert [(c.key, c.text) for c in criteria] == [
        ("AC-1", "Users can sign in with email"),
        ("AC-2", "Wrong password shows an error"),
        ("AC-3", "Locked accounts cannot sign in"),
        ("AC-4", "Error text is translated"),
        ("AC-5", "Given a signed in user When the session expires Then they are asked to sign in again"),
    ]


def test_requirements_come_from_issues_and_specs_with_notes_for_gaps() -> None:
    linked = IssueRef("octo", "app", 12)
    source = FakeSource(
        body="Closes #12, fixes #99. Spec: [s](docs/specs/missing.md)",
        closing=(linked,),
        issues={linked: Issue(linked, "Login", "- [ ] Email sign in")},
        files=(ChangedFile(path="docs/specs/login.md", status="added"),),
        head={"docs/specs/login.md": "# Login spec\nPlain prose only.\n"},
    )

    requirements, notes = collect_requirements(source, source.info(), source.files, GLOBS, ())

    assert [(r.source, r.title, len(r.criteria)) for r in requirements] == [
        ("issue#12", "Login", 1),
        ("docs/specs/login.md", "Login spec", 0),
    ]
    assert notes == (
        "Could not read issue#99; it is left out of the requirement check.",
        "Linked spec docs/specs/missing.md does not exist at the head commit.",
        "docs/specs/login.md has no structured acceptance criteria; a reviewer infers them from the text.",
    )


def test_dot_segments_in_an_issue_reference_are_rejected() -> None:
    assert parse_issue_refs(["Fixes ../..#5", "Closes ./x#6", "fixes octo/..#7"], "octo/app") == ()


def test_issues_in_other_repositories_need_an_allow_list() -> None:
    other = IssueRef("otherorg", "private", 1)
    source = FakeSource(
        body="Fixes otherorg/private#1",
        issues={other: Issue(other, "Secret", "- [ ] hidden criterion")},
    )

    blocked, notes = collect_requirements(source, source.info(), (), GLOBS, ())
    allowed, _ = collect_requirements(source, source.info(), (), GLOBS, ("OtherOrg/Private",))

    assert blocked == ()
    assert notes == (
        "otherorg/private#1 is in another repository; list it under issue_repos in .bylaw.toml to use it.",
    )
    assert [r.source for r in allowed] == ["otherorg/private#1"]


def test_maintainer_comments_join_the_requirement_text_but_not_its_criteria() -> None:
    linked = IssueRef("octo", "app", 7)
    source = FakeSource(
        commits=("Closes #7",),
        issues={linked: Issue(linked, "Login", "- [ ] Email sign in", ("- [ ] Lock after five failures",))},
    )

    (requirement,), _ = collect_requirements(source, source.info(), (), (), ())

    assert "## Comments from maintainers" in requirement.text
    assert "Lock after five failures" in requirement.text
    assert [c.text for c in requirement.criteria] == ["Email sign in"]
