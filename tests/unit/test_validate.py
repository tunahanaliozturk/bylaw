from bylaw.model import (
    AddedLine,
    Category,
    ChangedFile,
    Criterion,
    CriterionResult,
    CriterionStatus,
    Decision,
    FileRules,
    Finding,
    LinterRules,
    Location,
    Requirement,
    ReviewContext,
    ReviewResult,
    RuleKind,
    RuleSource,
    ScopeCreep,
    Severity,
)
from bylaw.validate import validate

CONTEXT = ReviewContext(
    base_sha="b",
    head_sha="h",
    title="t",
    files=(
        ChangedFile(
            path="app.py",
            status="modified",
            added_lines=tuple(AddedLine(number=n, text=f"line {n}") for n in (3, 4, 5)),
        ),
        ChangedFile(path="old.py", status="removed"),
    ),
    rules=(RuleSource(path="CONTRIBUTING.md", kind=RuleKind.PROSE, text="one\ntwo\nthree\n"),),
    requirements=(
        Requirement(
            source="issue#1", title="Login", text="", criteria=(Criterion(key="AC-1", text="Sign in"),)
        ),
    ),
    findings=(),
    notes=(),
)


def _finding(
    file: str = "app.py",
    start: int = 3,
    end: int = 3,
    category: Category = Category.SECURITY,
    evidence: str | None = None,
) -> Finding:
    return Finding(
        file=file,
        line_start=start,
        line_end=end,
        category=category,
        severity=Severity.HIGH,
        message="m",
        evidence=evidence,
    )


def _dropped(*findings: Finding) -> tuple[str, ...]:
    return validate(CONTEXT, ReviewResult(findings=findings)).dropped


def test_a_backed_finding_survives() -> None:
    kept = validate(CONTEXT, ReviewResult(findings=(_finding(evidence="CONTRIBUTING.md:2"),)))

    assert len(kept.result.findings) == 1
    assert kept.dropped == ()


def test_findings_outside_the_added_lines_are_dropped() -> None:
    assert _dropped(_finding(file="other.py")) == ("other.py:3 security: file is not part of the change",)
    assert _dropped(_finding(file="old.py")) == ("old.py:3 security: file is not part of the change",)
    assert _dropped(_finding(start=2, end=3)) == ("app.py:2 security: lines are not added by this change",)
    assert _dropped(_finding(start=5, end=4)) == ("app.py:5 security: line range is reversed",)


def test_rule_and_requirement_findings_need_evidence() -> None:
    assert _dropped(_finding(category=Category.RULE)) == (
        "app.py:3 rule: rule and requirement findings need evidence",
    )
    assert _dropped(_finding(category=Category.BUG)) == ()


def test_invented_citations_are_dropped() -> None:
    assert _dropped(_finding(evidence="CONTRIBUTING.md:9")) == (
        "app.py:3 security: evidence CONTRIBUTING.md:9 cites nothing bylaw collected",
    )
    assert _dropped(_finding(evidence="SECURITY.md:1")) != ()
    assert _dropped(_finding(category=Category.REQUIREMENT, evidence="issue#1/AC-1")) == ()
    assert _dropped(_finding(category=Category.REQUIREMENT, evidence="issue#1/AC-7")) != ()


def test_a_second_finding_on_the_same_lines_and_category_is_dropped() -> None:
    assert _dropped(_finding(), _finding()) == (
        "app.py:3 security: duplicates another finding on the same lines",
    )


def test_two_different_problems_on_the_same_lines_and_category_are_both_kept() -> None:
    injection = _finding().model_copy(update={"message": "Shell command built from the file name."})
    traversal = _finding().model_copy(update={"message": "The file name can climb out of the upload folder."})

    kept = validate(CONTEXT, ReviewResult(findings=(injection, traversal)))

    assert kept.result.findings == (injection, traversal)
    assert kept.dropped == ()


def test_criteria_results_keep_only_known_criteria_and_changed_locations() -> None:
    result = ReviewResult(
        criteria=(
            CriterionResult(
                criterion="issue#1/AC-1",
                status=CriterionStatus.MET,
                code=(Location(file="app.py", line=4), Location(file="elsewhere.py", line=1)),
            ),
            CriterionResult(criterion="issue#1/AC-9", status=CriterionStatus.MET),
            CriterionResult(criterion="issue#1/AC-1", status=CriterionStatus.MISSING),
        )
    )

    validated = validate(CONTEXT, result)

    assert [(c.criterion, c.code) for c in validated.result.criteria] == [
        ("issue#1/AC-1", (Location(file="app.py", line=4),))
    ]
    assert validated.dropped == (
        "issue#1/AC-1: 1 location(s) outside the change",
        "issue#1/AC-9: no such acceptance criterion",
        "issue#1/AC-1: duplicate criterion result",
    )


def test_scope_creep_must_point_at_an_added_line() -> None:
    result = ReviewResult(
        scope_creep=(
            ScopeCreep(file="app.py", line=5, message="new endpoint"),
            ScopeCreep(file="app.py", line=1, message="x"),
        )
    )

    validated = validate(CONTEXT, result)

    assert [s.line for s in validated.result.scope_creep] == [5]
    assert validated.dropped == ("app.py:1 scope creep: not an added line",)


def test_a_range_must_be_added_lines_all_the_way_through() -> None:
    gap = CONTEXT.model_copy(
        update={
            "files": (
                ChangedFile(
                    path="app.py",
                    status="modified",
                    added_lines=tuple(AddedLine(number=n, text="x") for n in (10, 50)),
                ),
            )
        }
    )

    kept = validate(CONTEXT, ReviewResult(findings=(_finding(start=3, end=5),)))
    split = validate(gap, ReviewResult(findings=(_finding(start=10, end=50),)))

    assert kept.dropped == ()
    assert split.dropped == ("app.py:10 security: lines are not added by this change",)


PROSE = CONTEXT.model_copy(
    update={
        "requirements": (
            *CONTEXT.requirements,
            Requirement(
                source="issue#7",
                title="Lockout",
                text="Lock accounts after failures.",
                criteria=(),
                inferable=True,
            ),
        )
    }
)


def _inferred(key: str = "issue#7/IC-1", text: str | None = "Locks after five failures") -> CriterionResult:
    return CriterionResult(criterion=key, status=CriterionStatus.MISSING, text=text)


def test_an_inferred_criterion_is_kept_for_a_requirement_without_criteria() -> None:
    checked = validate(PROSE, ReviewResult(criteria=(_inferred(),)))

    assert [c.criterion for c in checked.result.criteria] == ["issue#7/IC-1"]
    assert checked.dropped == ()


def test_an_inferred_criterion_is_dropped_where_criteria_are_listed() -> None:
    checked = validate(PROSE, ReviewResult(criteria=(_inferred("issue#1/IC-1"),)))

    assert checked.result.criteria == ()
    assert checked.dropped == ("issue#1/IC-1: no such acceptance criterion",)


def test_an_inferred_criterion_without_text_is_dropped() -> None:
    checked = validate(PROSE, ReviewResult(criteria=(_inferred(text=None),)))

    assert checked.dropped == ("issue#7/IC-1: inferred criterion needs text",)


def test_more_than_five_inferred_criteria_are_dropped() -> None:
    checked = validate(PROSE, ReviewResult(criteria=(_inferred("issue#7/IC-6"),)))

    assert checked.dropped == ("issue#7/IC-6: no such acceptance criterion",)


def test_a_requirement_finding_may_cite_an_inferred_criterion() -> None:
    finding = _finding(category=Category.REQUIREMENT, evidence="issue#7/IC-1")

    checked = validate(PROSE, ReviewResult(findings=(finding,), criteria=(_inferred(),)))

    assert checked.result.findings == (finding,)


def test_a_discussed_issue_with_a_checklist_may_add_inferred_criteria() -> None:
    discussed = CONTEXT.model_copy(
        update={"requirements": (CONTEXT.requirements[0].model_copy(update={"inferable": True}),)}
    )

    checked = validate(discussed, ReviewResult(criteria=(_inferred("issue#1/IC-1"),)))

    assert [c.criterion for c in checked.result.criteria] == ["issue#1/IC-1"]


def test_inferred_criterion_text_that_is_blank_or_too_long_is_dropped() -> None:
    blank = _inferred(text="   ")
    long = _inferred("issue#7/IC-2", text="x" * 301)

    checked = validate(PROSE, ReviewResult(criteria=(blank, long)))

    assert checked.dropped == (
        "issue#7/IC-1: inferred criterion needs text",
        "issue#7/IC-2: inferred criterion text is too long",
    )


MONOREPO = CONTEXT.model_copy(
    update={
        "files": tuple(
            ChangedFile(path=path, status="modified", added_lines=(AddedLine(number=3, text="x"),))
            for path in ("packages/api/app.py", "packages/worker/jobs.py")
        ),
        "rules": (
            RuleSource(path="AGENTS.md", kind=RuleKind.PROSE, text="root\n"),
            RuleSource(
                path="packages/api/AGENTS.md", kind=RuleKind.PROSE, text="a\nb\n", directory="packages/api"
            ),
            RuleSource(
                path="packages/worker/AGENTS.md", kind=RuleKind.PROSE, text="c\n", directory="packages/worker"
            ),
        ),
    }
)


def test_a_finding_may_cite_a_rule_file_of_its_own_package() -> None:
    finding = _finding("packages/api/app.py", category=Category.RULE, evidence="packages/api/AGENTS.md:2")
    root = _finding("packages/api/app.py", category=Category.RULE, evidence="AGENTS.md:1")

    kept = validate(MONOREPO, ReviewResult(findings=(finding, root.model_copy(update={"message": "r"}))))

    assert kept.dropped == ()
    assert len(kept.result.findings) == 2


def test_a_finding_that_cites_another_packages_rule_is_dropped() -> None:
    finding = _finding("packages/api/app.py", category=Category.RULE, evidence="packages/worker/AGENTS.md:1")

    dropped = validate(MONOREPO, ReviewResult(findings=(finding,))).dropped

    assert dropped == (
        "packages/api/app.py:3 rule: evidence packages/worker/AGENTS.md:1 is a rule of packages/worker, "
        "not of this file",
    )


def _linted(*rules: RuleSource) -> ReviewContext:
    files = (
        "app.py",
        "packages/api/db.py",
        "packages/api/tests/test_db.py",
        "packages/web/app.ts",
        "Orders.cs",
    )
    return CONTEXT.model_copy(
        update={
            "files": tuple(
                ChangedFile(path=path, status="modified", added_lines=(AddedLine(number=3, text="x"),))
                for path in files
            ),
            "rules": rules,
        }
    )


ROOT_RUFF = RuleSource(
    path="ruff.toml", kind=RuleKind.LINTER, text="", linter=LinterRules(tool="ruff", select=("E",))
)
API_RUFF = RuleSource(
    path="packages/api/ruff.toml",
    kind=RuleKind.LINTER,
    text="",
    directory="packages/api",
    linter=LinterRules(
        tool="ruff", select=("S",), per_file=(FileRules(pattern="tests/**", ignore=("S101",)),)
    ),
)


def _cites(context: ReviewContext, file: str, evidence: str) -> tuple[str, ...]:
    return validate(context, ReviewResult(findings=(_finding(file, evidence=evidence),))).dropped


def test_a_finding_may_cite_a_rule_id_its_linter_configuration_enables() -> None:
    context = _linted(ROOT_RUFF, API_RUFF)

    assert _cites(context, "packages/api/db.py", "ruff:S608") == ()
    assert _cites(context, "packages/api/db.py", "ruff:s608") == ()
    assert _cites(context, "app.py", "ruff:E711") == ()


def test_a_cited_rule_id_the_configuration_does_not_enable_is_dropped() -> None:
    dropped = _cites(_linted(ROOT_RUFF, API_RUFF), "app.py", "ruff:S608")

    assert dropped == ("app.py:3 security: evidence ruff:S608 is not enabled for this file by ruff.toml",)


def test_the_nearest_ruff_configuration_alone_decides() -> None:
    dropped = _cites(_linted(ROOT_RUFF, API_RUFF), "packages/api/db.py", "ruff:E711")

    assert dropped == (
        "packages/api/db.py:3 security: evidence ruff:E711 is not enabled for this file by "
        "packages/api/ruff.toml",
    )


def test_a_rule_id_switched_off_for_the_file_is_dropped() -> None:
    assert _cites(_linted(API_RUFF), "packages/api/tests/test_db.py", "ruff:S101") != ()
    assert _cites(_linted(API_RUFF), "packages/api/db.py", "ruff:S101") == ()


def test_a_rule_id_of_a_linter_with_no_configuration_for_the_file_is_dropped() -> None:
    dropped = _cites(_linted(API_RUFF), "app.py", "ruff:S608")

    assert dropped == ("app.py:3 security: evidence ruff:S608 cites no ruff configuration bylaw read",)


def test_an_eslint_package_config_that_is_silent_on_a_rule_leaves_it_to_the_root_config() -> None:
    root = RuleSource(
        path=".eslintrc.json",
        kind=RuleKind.LINTER,
        text="",
        linter=LinterRules(tool="eslint", select=("eqeqeq",), ignore=("no-alert",)),
    )
    web = RuleSource(
        path="packages/web/.eslintrc.yml",
        kind=RuleKind.LINTER,
        text="",
        directory="packages/web",
        linter=LinterRules(tool="eslint", select=("no-alert",)),
    )
    context = _linted(root, web)

    assert _cites(context, "packages/web/app.ts", "eslint:eqeqeq") == ()
    assert _cites(context, "packages/web/app.ts", "eslint:no-alert") == ()
    assert _cites(context, "packages/web/app.ts", "eslint:no-console") != ()


def test_a_rule_id_cited_on_a_file_of_another_language_is_dropped() -> None:
    dropped = _cites(_linted(ROOT_RUFF), "packages/web/app.ts", "ruff:E711")

    assert dropped == (
        "packages/web/app.ts:3 security: evidence ruff:E711 cites no ruff configuration bylaw read",
    )


def _linter(path: str, rules: LinterRules, directory: str = "") -> RuleSource:
    return RuleSource(path=path, kind=RuleKind.LINTER, text="", directory=directory, linter=rules)


def test_an_id_an_incomplete_configuration_is_silent_on_is_kept() -> None:
    eslint = LinterRules(tool="eslint", select=("no-console",), ignore=("no-alert",), complete=False)
    context = _linted(_linter(".eslintrc.json", eslint))

    assert _cites(context, "packages/web/app.ts", "eslint:eqeqeq") == ()
    assert _cites(context, "packages/web/app.ts", "eslint:no-alert") != ()


def test_an_explicit_off_beats_an_incomplete_configuration_in_the_same_directory() -> None:
    editorconfig = RuleSource(
        path=".editorconfig",
        kind=RuleKind.EDITORCONFIG,
        text="",
        linter=LinterRules(tool="dotnet", per_file=(FileRules(pattern="*.cs", ignore=("CA2100",)),)),
    )
    props = _linter("Directory.Build.props", LinterRules(tool="dotnet", complete=False))
    context = _linted(props, editorconfig)

    assert _cites(context, "Orders.cs", "dotnet:CA2100") != ()
    assert _cites(context, "Orders.cs", "dotnet:CA1000") == ()


def test_an_id_every_complete_configuration_is_silent_on_is_dropped() -> None:
    eslint = LinterRules(tool="eslint", select=("no-console",))

    assert _cites(_linted(_linter(".eslintrc.json", eslint)), "packages/web/app.ts", "eslint:eqeqeq") != ()


def test_only_the_nearest_ruff_configuration_counts_even_when_bylaw_could_not_read_all_of_it() -> None:
    nested = _linter(
        "packages/api/ruff.toml",
        LinterRules(tool="ruff", ignore=("S101",), complete=False),
        directory="packages/api",
    )
    context = _linted(ROOT_RUFF, nested)

    assert _cites(context, "packages/api/db.py", "ruff:S608") == ()
    assert _cites(context, "packages/api/db.py", "ruff:S101") != ()


DECIDED = CONTEXT.model_copy(
    update={
        "decisions": (
            Decision(
                path="docs/adr/0002-sqlite.md",
                title="Use SQLite",
                status="Accepted",
                start=11,
                text="## Decision\n\nWe store everything in SQLite.",
            ),
        )
    }
)


def test_a_rule_finding_may_cite_a_decision_line_shown_in_the_brief() -> None:
    finding = _finding(category=Category.RULE, evidence="docs/adr/0002-sqlite.md:13")

    result = validate(DECIDED, ReviewResult(findings=(finding,)))

    assert result.dropped == ()


def test_a_citation_of_an_adr_line_the_brief_did_not_show_is_dropped() -> None:
    # Line 5 is the status section, 14 is past the decision, 0001 was never shown.
    for evidence in ("docs/adr/0002-sqlite.md:5", "docs/adr/0002-sqlite.md:14", "docs/adr/0001-json.md:3"):
        finding = _finding(category=Category.RULE, evidence=evidence)

        result = validate(DECIDED, ReviewResult(findings=(finding,)))

        assert result.result.findings == (), evidence


def test_rule_and_decision_lines_count_only_newlines_as_line_breaks() -> None:
    rule = RuleSource(path="CONTRIBUTING.md", kind=RuleKind.PROSE, text="One\u2028still one.\nTwo.\n")
    (decision,) = DECIDED.decisions
    odd = decision.model_copy(update={"text": "## Decision\nA\x0cB."})
    context = DECIDED.model_copy(update={"rules": (rule,), "decisions": (odd,)})
    kept = (
        _finding(start=n, end=n, category=Category.RULE, evidence=e)
        for n, e in ((3, "CONTRIBUTING.md:2"), (4, "docs/adr/0002-sqlite.md:12"))
    )
    gone = (
        _finding(start=n, end=n, category=Category.RULE, evidence=e)
        for n, e in ((3, "CONTRIBUTING.md:3"), (4, "docs/adr/0002-sqlite.md:13"))
    )

    assert validate(context, ReviewResult(findings=tuple(kept))).dropped == ()
    assert len(validate(context, ReviewResult(findings=tuple(gone))).dropped) == 2
