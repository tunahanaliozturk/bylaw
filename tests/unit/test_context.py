import pytest

from bylaw.config import ConfigError, load_config
from bylaw.context import build_context, generated_patterns, is_skipped
from bylaw.model import (
    AddedLine,
    Category,
    ChangedFile,
    FileRules,
    Finding,
    LinterRules,
    ReviewContext,
    ReviewResult,
    Severity,
)
from bylaw.prompt import render_input
from bylaw.validate import validate
from tests.unit.fakes import FakeSource


def _file(path: str, *lines: str) -> ChangedFile:
    added = tuple(AddedLine(number=n, text=t) for n, t in enumerate(lines, start=1))
    return ChangedFile(path=path, status="modified", added_lines=added)


def test_the_base_config_decides_even_when_the_change_edits_it() -> None:
    source = FakeSource(
        base={".bylaw.toml": 'spec_globs = ["specs/**"]\n'},
        head={
            ".bylaw.toml": 'spec_globs = ["other/**"]\n',
            "specs/a.md": "# A\n- [ ] one\n",
            "other/b.md": "# B\n- [ ] two\n",
        },
        files=(_file(".bylaw.toml", "x"), _file("specs/a.md", "x"), _file("other/b.md", "x")),
    )

    context = build_context(source)

    assert [r.source for r in context.requirements] == ["specs/a.md"]
    assert any(".bylaw.toml" in note and "base branch" in note for note in context.notes)


def test_lock_vendored_and_generated_files_are_skipped_with_a_note() -> None:
    source = FakeSource(
        base={".gitattributes": "api/*.gen.py linguist-generated=true\n"},
        files=(
            _file("uv.lock", "x"),
            _file("vendor/lib/a.go", "x"),
            _file("api/client.gen.py", "x"),
            _file("src/app.py", "x"),
        ),
    )

    context = build_context(source)

    assert [f.path for f in context.files] == ["src/app.py"]
    assert (
        "Skipped 3 lock, vendored or generated file(s): uv.lock, vendor/lib/a.go, api/client.gen.py."
        in context.notes
    )


def test_editorconfig_findings_and_rule_sources_are_included() -> None:
    source = FakeSource(
        base={".editorconfig": "root = true\n[*.py]\nindent_style = space\n", "CONTRIBUTING.md": "Be kind."},
        files=(_file("src/app.py", "def run():", "\treturn 1"),),
    )

    context = build_context(source)

    assert [(f.file, f.line_start, f.evidence) for f in context.findings] == [
        ("src/app.py", 2, ".editorconfig:3")
    ]
    assert [r.path for r in context.rules] == [".editorconfig", "CONTRIBUTING.md"]


def test_a_change_in_a_package_brings_its_agents_md_into_the_context() -> None:
    source = FakeSource(
        base={
            "AGENTS.md": "Root rules.",
            "packages/api/AGENTS.md": "Return errors as values.",
            "packages/worker/AGENTS.md": "Raise on errors.",
        },
        files=(_file("packages/api/src/handlers.py", "x = 1"),),
    )

    context = build_context(source)

    assert [(r.path, r.directory) for r in context.rules] == [
        ("AGENTS.md", ""),
        ("packages/api/AGENTS.md", "packages/api"),
    ]


def test_a_root_contributing_guide_under_github_stays_a_rule_for_the_whole_repository() -> None:
    source = FakeSource(
        base={".github/CONTRIBUTING.md": "Use parameterised SQL.", "docs/CONTRIBUTING.md": "Write docs."},
        files=(
            _file(".github/workflows/ci.yml", "on: push"),
            _file("docs/guide.md", "More."),
            _file("src/app.py", "x = 1"),
        ),
    )
    context = build_context(source)
    finding = Finding(
        file="src/app.py",
        line_start=1,
        line_end=1,
        category=Category.RULE,
        severity=Severity.MEDIUM,
        message="m",
        evidence=".github/CONTRIBUTING.md:1",
    )

    assert [(r.path, r.directory) for r in context.rules] == [
        (".github/CONTRIBUTING.md", ""),
        ("docs/CONTRIBUTING.md", ""),
    ]
    assert validate(context, ReviewResult(findings=(finding,))).dropped == ()
    assert "Rules for" not in render_input(context, nonce="feedc0de")[0]


def test_a_change_to_a_package_rule_file_is_noted_as_reviewed_against_the_base() -> None:
    source = FakeSource(
        base={"packages/api/AGENTS.md": "Return errors as values."},
        files=(_file("packages/api/AGENTS.md", "Raise instead."),),
    )

    context = build_context(source)

    assert any("packages/api/AGENTS.md" in note and "base branch" in note for note in context.notes)


def test_a_context_written_before_nested_rules_still_loads() -> None:
    old = (
        '{"base_sha": "b", "head_sha": "h", "title": "t", "files": [], "requirements": [], "findings": [],'
        ' "notes": [], "rules": [{"path": "AGENTS.md", "kind": "prose", "text": "Be kind."}]}'
    )

    context = ReviewContext.model_validate_json(old)

    assert (context.rules[0].directory, context.rules[0].linter) == ("", None)


def test_the_rule_ids_ruff_enables_are_parsed_into_the_context() -> None:
    source = FakeSource(
        base={
            "pyproject.toml": (
                "[tool.ruff.lint]\nselect = ['S']\n[tool.ruff.lint.per-file-ignores]\n'tests/**' = ['S101']\n"
            )
        },
        files=(_file("app/db.py", "x = 1"),),
    )

    context = build_context(source)

    assert context.rules[0].linter == LinterRules(
        tool="ruff", select=("S",), per_file=(FileRules(pattern="tests/**", ignore=("S101",)),)
    )
    assert ReviewContext.model_validate_json(context.model_dump_json()) == context


def test_the_context_survives_a_json_round_trip() -> None:
    source = FakeSource(files=(_file("src/app.py", "x = 'Öztürk'"),))

    context = build_context(source)

    assert ReviewContext.model_validate_json(context.model_dump_json()) == context


def test_gitattributes_patterns_without_a_slash_match_at_any_depth() -> None:
    patterns = generated_patterns("*.pb.go linguist-generated\n# comment\n/dist/** linguist-vendored\n")

    assert is_skipped("svc/api/types.pb.go", patterns)
    assert is_skipped("dist/app.js", patterns)
    assert not is_skipped("src/dist/app.js", patterns)


def test_an_invalid_config_names_the_file() -> None:
    with pytest.raises(ConfigError, match=r"\.bylaw\.toml"):
        load_config("unknown_key = 1\n")


def test_config_defaults_match_the_design() -> None:
    config = load_config(None)

    assert (config.severity_threshold, config.max_comments, config.issue_repos) == ("medium", 15, ())
    assert (config.incremental, config.budget.pr_tokens) == (True, None)


def test_incremental_review_and_a_token_budget_are_set_in_the_config() -> None:
    config = load_config("incremental = false\n\n[budget]\npr_tokens = 200000\n")

    assert (config.incremental, config.budget.pr_tokens) == (False, 200_000)
    with pytest.raises(ConfigError):
        load_config("[budget]\npr_tokens = 10\n")


def test_an_invalid_editorconfig_glob_is_ignored_with_a_note() -> None:
    source = FakeSource(
        base={".editorconfig": "root = true\n[[z-a].py]\nindent_style = tab\n[*.py]\nindent_style = space\n"},
        files=(_file("src/app.py", "def run():", "\treturn 1"),),
    )

    context = build_context(source)

    assert [f.line_start for f in context.findings] == [2]
    assert ".editorconfig: section [[z-a].py] is not a valid pattern and was ignored." in context.notes


def test_a_long_skip_list_is_capped() -> None:
    source = FakeSource(files=tuple(_file(f"vendor/p{n}.go", "x") for n in range(12)))

    context = build_context(source)

    (note,) = context.notes
    assert note.startswith("Skipped 12 lock, vendored or generated file(s): vendor/p0.go,")
    assert note.endswith("and 2 more.")


def test_files_without_a_patch_get_a_note_that_says_why() -> None:
    files = (
        ChangedFile(path="logo.png", status="modified", patch_omitted=True, changes=0),
        ChangedFile(path="moved.py", status="renamed", previous_path="old.py", patch_omitted=True, changes=0),
        ChangedFile(path="huge.sql", status="added", patch_omitted=True, changes=90000),
        ChangedFile(path="blob.bin", status="added", patch_omitted=True),
    )

    notes = build_context(FakeSource(files=files)).notes

    assert "logo.png: binary, empty or permission-only change, nothing to review." in notes
    assert not any("moved.py" in note for note in notes)
    assert "huge.sql: diff too large for GitHub to show, not reviewed." in notes
    assert "blob.bin: binary file, not reviewed." in notes


def test_a_pull_request_cut_short_by_the_file_listing_cap_says_so() -> None:
    source = FakeSource(files=(_file("a.py", "x"),), file_count=3200)

    notes = build_context(source).notes

    assert "GitHub lists at most 3000 files: 1 of 3200 changed files were read." in notes


def test_the_base_branch_comment_settings_travel_with_the_context() -> None:
    source = FakeSource(base={".bylaw.toml": 'severity_threshold = "high"\nmax_comments = 0\n'})

    context = build_context(source)

    assert (context.severity_threshold, context.max_comments) == ("high", 0)


def test_the_base_branch_token_budget_travels_with_the_context() -> None:
    source = FakeSource(base={".bylaw.toml": "input_token_budget = 50000\n"})

    assert build_context(source).input_tokens == 50000


def test_a_token_budget_outside_the_limits_is_a_config_error() -> None:
    with pytest.raises(ConfigError):
        load_config("input_token_budget = 5\n")
