import pytest

from bylaw.linters import describe, enables, parse
from bylaw.model import FileRules, LinterRules


def _parsed(path: str, text: str) -> LinterRules:
    rules = parse(path, text)
    assert rules is not None
    return rules


# Ruff (LNT-1)


def test_ruff_rules_come_from_the_lint_table_of_ruff_toml() -> None:
    text = """
line-length = 100
[lint]
select = ["E", "S"]
extend-select = ["B006"]
ignore = ["E501"]
[lint.per-file-ignores]
"tests/**" = ["S101"]
"""

    assert _parsed("ruff.toml", text) == LinterRules(
        tool="ruff",
        select=("E", "S", "B006"),
        ignore=("E501",),
        per_file=(FileRules(pattern="tests/**", ignore=("S101",)),),
    )


def test_ruff_rules_in_pyproject_are_read_from_tool_ruff_with_the_old_top_level_keys_too() -> None:
    text = """
[project]
name = "api"
[tool.ruff]
select = ["F"]
extend-ignore = ["F401"]
[tool.ruff.lint]
extend-select = ["UP"]
[tool.ruff.lint.extend-per-file-ignores]
"__init__.py" = ["F403"]
"""

    rules = _parsed("packages/api/pyproject.toml", text)

    assert (rules.select, rules.ignore) == (("F", "UP"), ("F401",))
    assert rules.per_file == (FileRules(pattern="__init__.py", ignore=("F403",)),)


def test_ruff_without_a_select_enables_its_default_rules() -> None:
    rules = _parsed(".ruff.toml", "[lint]\nextend-select = ['S']\n")

    assert rules.select == ("E4", "E7", "E9", "F", "S")


def test_a_ruff_extend_is_followed_on_the_base_branch() -> None:
    base = {
        "pyproject.toml": (
            '[tool.ruff.lint]\nselect = ["E", "S"]\nignore = ["E501"]\n'
            '[tool.ruff.lint.per-file-ignores]\n"packages/api/tests/**" = ["S101"]\n'
            '"conftest.py" = ["F401"]\n"docs/**" = ["E"]\n'
        ),
    }
    text = 'extend = "../../pyproject.toml"\n[lint]\nextend-select = ["B"]\n'

    rules = parse("packages/api/ruff.toml", text, base.get)

    assert rules is not None
    assert (rules.select, rules.ignore, rules.complete) == (("E", "S", "B"), ("E501",), True)
    # Patterns of the extended file are relative to its own directory; ones that cannot reach this
    # package are left out.
    assert rules.per_file == (
        FileRules(pattern="tests/**", ignore=("S101",)),
        FileRules(pattern="conftest.py", ignore=("F401",)),
    )
    assert rules.notes == ("extends pyproject.toml, read from the base branch",)
    assert enables(rules, "S608", "app/db.py") is True


def test_a_child_select_replaces_what_the_extended_ruff_config_selected() -> None:
    base = {"ruff.toml": '[lint]\nselect = ["E"]\nignore = ["E501"]\n'}

    rules = parse("pkg/ruff.toml", 'extend = "../ruff.toml"\n[lint]\nselect = ["S"]\n', base.get)

    assert rules is not None
    assert (rules.select, rules.ignore) == (("S",), ())


def test_a_ruff_extend_that_cannot_be_read_leaves_the_config_incomplete() -> None:
    empty: dict[str, str] = {}
    rules = parse("pkg/ruff.toml", 'extend = "../missing.toml"\n[lint]\nignore = ["S101"]\n', empty.get)

    assert rules is not None
    assert rules.complete is False
    assert rules.notes == ("extends ../missing.toml, which bylaw could not read",)
    assert enables(rules, "S608", "app.py") is None
    assert enables(rules, "S101", "app.py") is False


def test_a_ruff_extend_outside_the_repository_or_in_a_loop_is_not_followed() -> None:
    asked: list[str] = []
    base = {"ruff.toml": 'extend = "a/ruff.toml"\n', "a/ruff.toml": 'extend = "../ruff.toml"\n'}

    def read(path: str) -> str | None:
        asked.append(path)
        return base.get(path)

    outside = parse("a/ruff.toml", 'extend = "../../etc/ruff.toml"\n', read)
    loop = parse("a/ruff.toml", base["a/ruff.toml"], read)

    assert outside is not None
    assert outside.complete is False
    assert loop is not None
    assert loop.complete is False
    assert asked == ["ruff.toml"]


def test_a_broken_ruff_config_is_reported_rather_than_guessed() -> None:
    with pytest.raises(ValueError, match="TOML"):
        parse("ruff.toml", "[lint\nselect = ['S']\n")


@pytest.mark.parametrize(
    ("code", "on"),
    [
        ("S608", True),
        ("E711", True),
        ("E501", False),
        ("ERA001", False),  # "E" is pycodestyle, not eradicate
        ("B006", True),
        ("B007", False),
        ("PLR0913", True),  # "PL" covers PLC, PLE, PLR and PLW
        ("S101", True),
    ],
)
def test_ruff_selectors_enable_codes_by_prefix_and_the_more_specific_one_wins(code: str, on: bool) -> None:
    rules = LinterRules(tool="ruff", select=("E", "S", "B006", "PL"), ignore=("E501",))

    assert enables(rules, code, "app/users.py") is on


def test_ruff_per_file_ignores_switch_a_code_off_for_matching_files_only() -> None:
    rules = LinterRules(
        tool="ruff", select=("S",), per_file=(FileRules(pattern="tests/**", ignore=("S101",)),)
    )

    assert enables(rules, "S101", "tests/test_users.py") is False
    assert enables(rules, "S101", "app/users.py") is True


def test_ruff_all_is_the_least_specific_selector() -> None:
    rules = LinterRules(tool="ruff", select=("ALL",), ignore=("D",))

    assert enables(rules, "S608", "a.py") is True
    assert enables(rules, "D100", "a.py") is False


# ESLint (LNT-2)


def test_eslint_rules_are_read_from_a_json_config_with_comments() -> None:
    text = """{
  // the team's rules
  "extends": ["eslint:recommended"],
  "rules": {
    "no-console": "error",
    "eqeqeq": ["warn", "always"],
    "no-var": "off",
    "semi": 0,
    "url": "https://example.com/*not a comment*/"
  },
  /* tests may log */
  "overrides": [{"files": ["*.test.ts"], "rules": {"no-console": "off", "no-alert": 2}}]
}"""

    rules = _parsed(".eslintrc.json", text)

    assert rules.tool == "eslint"
    assert rules.select == ("no-console", "eqeqeq")
    assert rules.ignore == ("no-var", "semi")
    assert rules.per_file == (FileRules(pattern="*.test.ts", select=("no-alert",), ignore=("no-console",)),)
    assert rules.notes == ("extends eslint:recommended, whose rules are not listed",)


def test_eslint_rules_are_read_from_a_yaml_config() -> None:
    text = (
        "rules:\n  no-console: warn\n  '@typescript-eslint/no-floating-promises': [error]\n"
        "  no-debugger: off\n"
    )

    rules = _parsed(".eslintrc.yml", text)

    assert rules.select == ("no-console", "@typescript-eslint/no-floating-promises")
    assert rules.ignore == ("no-debugger",)


def test_yaml_tags_that_would_build_python_objects_are_refused() -> None:
    with pytest.raises(ValueError, match="YAML"):
        parse(".eslintrc.yaml", "rules: !!python/object/apply:os.system ['echo hi']\n")


def test_an_eslint_flat_config_in_javascript_stays_prose_and_is_never_run() -> None:
    assert parse("eslint.config.js", "export default [{ rules: { 'no-console': 'error' } }];\n") is None
    assert parse(".eslintrc.js", "module.exports = { rules: { 'no-console': 2 } };\n") is None


def test_eslint_overrides_decide_for_the_files_they_match() -> None:
    rules = LinterRules(
        tool="eslint",
        select=("no-console",),
        per_file=(FileRules(pattern="*.test.ts", ignore=("no-console",)),),
    )

    assert enables(rules, "no-console", "src/server.ts") is True
    assert enables(rules, "no-console", "src/server.test.ts") is False
    assert enables(rules, "eqeqeq", "src/server.ts") is None


# golangci-lint (LNT-3)


def test_golangci_v1_adds_enabled_linters_to_the_default_set() -> None:
    rules = _parsed(".golangci.yml", "linters:\n  enable: [gosec, revive]\n  disable: [errcheck]\n")

    assert rules.tool == "golangci-lint"
    assert set(rules.select) == {
        "gosimple",
        "govet",
        "ineffassign",
        "staticcheck",
        "unused",
        "gosec",
        "revive",
    }
    assert rules.ignore == ("errcheck",)


def test_golangci_v1_disable_all_keeps_only_the_enabled_linters() -> None:
    rules = _parsed(".golangci.yaml", "linters:\n  disable-all: true\n  enable:\n    - gosec\n")

    assert rules.select == ("gosec",)


def test_nested_yaml_aliases_are_ignored_instead_of_expanded_into_text() -> None:
    levels = ["a: &a [x, x, x, x, x, x, x, x, x, x]"]
    for previous, name in zip("abcde", "bcdef", strict=True):
        levels.append(f"{name}: &{name} [{', '.join([f'*{previous}'] * 10)}]")
    text = "\n".join(
        [*levels, "linters:", "  disable-all: true", "  enable: [gosec, *f]", "  disable: *f", ""]
    )

    rules = _parsed(".golangci.yml", text)

    assert (rules.select, rules.ignore) == (("gosec",), ())


def test_values_of_an_unexpected_type_are_skipped_rather_than_fatal() -> None:
    eslint = _parsed(
        ".eslintrc.yml", "rules:\n  a: [[error]]\n  b: {level: error}\noverrides: [{files: [[x]]}]\n"
    )
    golangci = _parsed(".golangci.yml", "version: [2]\nlinters:\n  default: [all]\n  enable: gosec\n")

    assert (eslint.select, eslint.ignore, eslint.per_file) == ((), (), ())
    assert "gosec" not in golangci.select


def test_configurations_with_settings_bylaw_does_not_read_are_marked_incomplete() -> None:
    eslint = _parsed(".eslintrc.json", '{"extends": "airbnb", "rules": {"no-console": "error"}}')
    override = _parsed(".eslintrc.json", '{"overrides": [{"files": "*.ts", "extends": ["x"]}]}')
    presets = _parsed(".golangci.yml", "linters:\n  presets: [bugs]\n  enable: [gosec]\n")
    fast = _parsed(".golangci.yml", 'version: "2"\nlinters:\n  default: fast\n')
    plain = _parsed(".eslintrc.json", '{"rules": {"no-console": "error"}}')

    assert [r.complete for r in (eslint, override, presets, fast, plain)] == [
        False,
        False,
        False,
        False,
        True,
    ]
    assert presets.notes == ("presets bugs, whose linters are not listed",)
    assert fast.notes == ("default set fast, whose linters are not listed",)
    assert enables(eslint, "eqeqeq", "a.ts") is None


def test_dotnet_category_and_global_severities_are_notes_that_leave_the_config_incomplete() -> None:
    editorconfig = _parsed(
        ".editorconfig", "[*.cs]\ndotnet_analyzer_diagnostic.category-Security.severity = error\n"
    )
    globalconfig = _parsed(
        ".globalconfig", "is_global = true\ndotnet_analyzer_diagnostic.severity = warning\n"
    )
    props = _parsed("Directory.Build.props", "<AnalysisLevel>latest-all</AnalysisLevel>")

    assert (editorconfig.complete, editorconfig.per_file) == (False, ())
    assert editorconfig.notes == ("for *.cs: category-security error; ids these turn on are not listed",)
    assert globalconfig.notes == ("all analyzers warning; ids these turn on are not listed",)
    assert (globalconfig.complete, props.complete) == (False, False)


def test_the_brief_says_when_an_unlisted_id_may_still_be_on() -> None:
    rules = LinterRules(tool="eslint", select=("no-console",), complete=False, notes=("extends airbnb, x",))

    assert describe(rules).endswith(
        "- bylaw did not read all that this configuration turns on, so an id not listed may still be on"
    )


def test_golangci_v2_reads_the_default_set_by_name() -> None:
    none = _parsed(".golangci.yml", 'version: "2"\nlinters:\n  default: none\n  enable: [gosec]\n')
    everything = _parsed(".golangci.yml", 'version: "2"\nlinters:\n  default: all\n  disable: [lll]\n')
    standard = _parsed(".golangci.yml", 'version: "2"\n')

    assert none.select == ("gosec",)
    assert (everything.select, everything.ignore) == (("*",), ("lll",))
    assert set(standard.select) == {"errcheck", "govet", "ineffassign", "staticcheck", "unused"}
    assert enables(everything, "gosec", "main.go") is True
    assert enables(everything, "lll", "main.go") is False


# .NET analyzers (LNT-4)


def test_dotnet_severities_in_editorconfig_sections_apply_to_the_files_they_match() -> None:
    text = """root = true
[*.cs]
dotnet_diagnostic.CA2100.severity = error
dotnet_diagnostic.ca1062.severity = none
dotnet_diagnostic.IDE0005.severity = default
indent_style = space
[tests/**.cs]
dotnet_diagnostic.CA2100.severity = silent
"""

    rules = _parsed(".editorconfig", text)

    assert rules.tool == "dotnet"
    assert rules.per_file == (
        FileRules(pattern="*.cs", select=("CA2100",), ignore=("CA1062",)),
        FileRules(pattern="tests/**.cs", ignore=("CA2100",)),
    )
    assert enables(rules, "CA2100", "src/Orders.cs") is True
    assert enables(rules, "CA2100", "tests/OrdersTests.cs") is False
    assert enables(rules, "CA1000", "src/Orders.cs") is None


def test_an_editorconfig_without_analyzer_settings_has_no_rule_ids() -> None:
    assert parse("packages/api/.editorconfig", "[*.py]\nindent_style = space\n") is None


def test_a_global_analyzer_config_applies_everywhere() -> None:
    rules = _parsed(".globalconfig", "is_global = true\ndotnet_diagnostic.CA2100.severity = warning\n")

    assert rules.select == ("CA2100",)


def test_the_dotnet_analysis_level_is_read_from_directory_build_props() -> None:
    text = """<Project>
  <PropertyGroup>
    <AnalysisLevel>latest-recommended</AnalysisLevel>
    <AnalysisModeSecurity>All</AnalysisModeSecurity>
  </PropertyGroup>
</Project>"""

    rules = _parsed("Directory.Build.props", text)

    assert rules.tool == "dotnet"
    assert rules.notes == (
        "AnalysisLevel latest-recommended, AnalysisModeSecurity All: ids these turn on are not listed",
    )


def test_the_brief_lists_what_a_finding_may_cite() -> None:
    rules = LinterRules(
        tool="ruff",
        select=("E", "S"),
        ignore=("E501",),
        per_file=(FileRules(pattern="tests/**", ignore=("S101",)),),
        notes=("extends ../ruff.toml, which bylaw does not read",),
    )

    assert describe(rules) == (
        "Rule ids a finding may cite as evidence, written ruff:<id>:\n"
        "- enabled: E, S (a prefix enables every id that starts with it)\n"
        "- disabled: E501\n"
        "- for tests/**: disabled S101\n"
        "- extends ../ruff.toml, which bylaw does not read"
    )


def test_a_double_star_in_a_linter_glob_also_matches_no_directory_at_all() -> None:
    eslint = LinterRules(
        tool="eslint",
        select=("no-console",),
        per_file=(FileRules(pattern="src/**/*.ts", ignore=("no-console",)),),
    )
    ruff = LinterRules(
        tool="ruff", select=("S",), per_file=(FileRules(pattern="**/tests/*.py", ignore=("S101",)),)
    )

    assert enables(eslint, "no-console", "src/a.ts") is False
    assert enables(eslint, "no-console", "src/deep/a.ts") is False
    assert enables(eslint, "no-console", "lib/a.ts") is True
    assert enables(ruff, "S101", "tests/test_a.py") is False
    assert enables(ruff, "S101", "app/tests/test_a.py") is False
    assert enables(ruff, "S101", "app/a.py") is True


def test_a_negated_ruff_per_file_pattern_applies_to_the_files_it_does_not_match() -> None:
    rules = LinterRules(
        tool="ruff", select=("S",), per_file=(FileRules(pattern="!src/**", ignore=("S101",)),)
    )

    assert enables(rules, "S101", "src/app.py") is True
    assert enables(rules, "S101", "scripts/seed.py") is False


def test_eslint_severities_are_read_whatever_their_case() -> None:
    rules = _parsed(
        ".eslintrc.json", '{"rules": {"no-console": "Error", "eqeqeq": ["WARN"], "no-var": "OFF"}}'
    )

    assert (rules.select, rules.ignore) == (("no-console", "eqeqeq"), ("no-var",))
