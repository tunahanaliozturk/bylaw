from dataclasses import dataclass, field

from bylaw.model import ChangedFile, FileRules, LinterRules, RuleKind
from bylaw.rules import MAX_RULE_DIRECTORIES, RULE_PATHS, collect_rules, is_rule_file
from tests.unit.fakes import FakeSource


def _changed(*paths: str) -> list[ChangedFile]:
    return [ChangedFile(path=p, status="modified") for p in paths]


@dataclass
class CountingSource(FakeSource):
    listed: list[str] = field(default_factory=list)

    def list_base(self, directory: str) -> frozenset[str]:
        self.listed.append(directory)
        return super().list_base(directory)


def test_prose_rules_that_exist_on_the_base_are_collected() -> None:
    base = {"CONTRIBUTING.md": "Use parameterised queries.", "AGENTS.md": "Run the tests."}

    rules, _ = collect_rules(_changed("README.md"), FakeSource(base=base), [])

    assert [(r.path, r.kind) for r in rules] == [
        ("CONTRIBUTING.md", RuleKind.PROSE),
        ("AGENTS.md", RuleKind.PROSE),
    ]


def test_linter_configuration_follows_the_languages_in_the_diff() -> None:
    source = FakeSource(base={"ruff.toml": "line-length = 100", ".golangci.yml": "linters: {}"})

    python_rules, _ = collect_rules(_changed("app.py"), source, [])
    docs_rules, _ = collect_rules(_changed("README.md"), source, [])

    assert [r.path for r in python_rules] == ["ruff.toml"]
    assert docs_rules == ()


def test_pyproject_counts_only_when_it_configures_ruff() -> None:
    with_ruff = FakeSource(base={"pyproject.toml": "[project]\n[tool.ruff]\nline-length = 100\n"})
    without_ruff = FakeSource(base={"pyproject.toml": "[project]\nname = 'x'\n"})

    assert [r.path for r in collect_rules(_changed("a.py"), with_ruff, [])[0]] == ["pyproject.toml"]
    assert collect_rules(_changed("a.py"), without_ruff, [])[0] == ()


def test_editorconfig_files_already_read_are_passed_through_first() -> None:
    files = [(".editorconfig", "root = true"), ("packages/api/.editorconfig", "[*]")]

    rules, _ = collect_rules(_changed("a.py"), FakeSource(), files)

    assert [(r.path, r.kind, r.directory) for r in rules] == [
        (".editorconfig", RuleKind.EDITORCONFIG, ""),
        ("packages/api/.editorconfig", RuleKind.EDITORCONFIG, "packages/api"),
    ]


def test_rule_paths_include_the_bylaw_config_but_not_pyproject() -> None:
    assert ".bylaw.toml" in RULE_PATHS
    assert "CONTRIBUTING.md" in RULE_PATHS
    assert "pyproject.toml" not in RULE_PATHS


def test_a_package_rule_file_counts_as_a_rule_file_wherever_it_sits() -> None:
    assert is_rule_file("packages/api/AGENTS.md")
    assert is_rule_file("packages/api/ruff.toml")
    assert is_rule_file("packages/api/.editorconfig")
    assert not is_rule_file("packages/api/pyproject.toml")
    assert not is_rule_file("packages/api/README.md")


def test_a_change_in_a_package_is_reviewed_against_its_own_agents_md_and_the_root_rules() -> None:
    source = FakeSource(
        base={
            "AGENTS.md": "Root rules.",
            "packages/api/AGENTS.md": "Return errors as values.",
            "packages/worker/AGENTS.md": "Raise on errors.",
        }
    )

    rules, notes = collect_rules(_changed("packages/api/src/handlers.py"), source, [])

    assert [(r.path, r.kind, r.directory) for r in rules] == [
        ("AGENTS.md", RuleKind.PROSE, ""),
        ("packages/api/AGENTS.md", RuleKind.PROSE, "packages/api"),
    ]
    assert notes == ()


def test_the_nearest_file_of_each_name_applies_and_farther_ones_are_left_out() -> None:
    source = FakeSource(
        base={
            "packages/AGENTS.md": "Shared package rules.",
            "packages/CLAUDE.md": "Shared notes.",
            "packages/api/AGENTS.md": "API rules.",
        }
    )

    api, _ = collect_rules(_changed("packages/api/app.py"), source, [])
    web, _ = collect_rules(_changed("packages/web/app.ts"), source, [])

    assert [r.path for r in api] == ["packages/CLAUDE.md", "packages/api/AGENTS.md"]
    assert [r.path for r in web] == ["packages/AGENTS.md", "packages/CLAUDE.md"]


def test_a_package_linter_config_is_read_for_the_languages_changed_under_it() -> None:
    source = FakeSource(
        base={
            "packages/api/ruff.toml": "[lint]\nselect = ['S']\n",
            "packages/api/pyproject.toml": "[project]\nname = 'api'\n",
            "packages/pyproject.toml": "[tool.ruff]\nline-length = 90\n",
            "packages/api/.golangci.yml": "linters: {}\n",
        }
    )

    python, _ = collect_rules(_changed("packages/api/app.py"), source, [])
    docs, _ = collect_rules(_changed("packages/api/README.md"), source, [])

    assert [(r.path, r.kind) for r in python] == [
        ("packages/pyproject.toml", RuleKind.LINTER),
        ("packages/api/ruff.toml", RuleKind.LINTER),
    ]
    assert docs == ()


def test_only_directories_that_hold_changed_files_are_listed() -> None:
    source = CountingSource(base={"packages/api/AGENTS.md": "x", "packages/web/AGENTS.md": "y"})

    collect_rules(
        [*_changed("packages/api/a.py", "packages/api/b.py"), ChangedFile(path="old/x.py", status="removed")],
        source,
        [],
    )

    assert sorted(source.listed) == ["packages", "packages/api"]


def test_directories_past_the_cap_are_not_read_and_the_notes_say_so() -> None:
    paths = [f"pkg{n:02}/app.py" for n in range(MAX_RULE_DIRECTORIES + 2)]
    source = CountingSource(base={f"pkg{n:02}/AGENTS.md": "x" for n in range(MAX_RULE_DIRECTORIES + 2)})

    rules, notes = collect_rules(_changed(*paths), source, [])

    assert len(source.listed) == MAX_RULE_DIRECTORIES
    assert len(rules) == MAX_RULE_DIRECTORIES
    assert notes == (
        f"Rule files were looked for in {MAX_RULE_DIRECTORIES} of the {MAX_RULE_DIRECTORIES + 2} "
        "directories that hold changed files, the ones nearest the root; pkg40, pkg41 were not read.",
    )


def test_the_rule_ids_a_linter_config_enables_travel_with_its_rule_source() -> None:
    source = FakeSource(
        base={
            "packages/api/ruff.toml": "[lint]\nselect = ['S']\n",
            "packages/api/.eslintrc.yml": "rules:\n  no-console: error\n",
            "AGENTS.md": "Be kind.",
        }
    )

    rules, notes = collect_rules(_changed("packages/api/app.py", "packages/api/web.ts"), source, [])

    linters = {r.path: r.linter for r in rules}
    assert linters["AGENTS.md"] is None
    assert linters["packages/api/ruff.toml"] == LinterRules(tool="ruff", select=("S",))
    assert linters["packages/api/.eslintrc.yml"] == LinterRules(tool="eslint", select=("no-console",))
    assert notes == ()


def test_dotnet_analyzer_settings_in_an_editorconfig_are_read_as_rule_ids() -> None:
    files = [(".editorconfig", "[*.cs]\ndotnet_diagnostic.CA2100.severity = error\n")]

    rules, _ = collect_rules(_changed("Orders.cs"), FakeSource(), files)

    assert rules[0].linter == LinterRules(
        tool="dotnet", per_file=(FileRules(pattern="*.cs", select=("CA2100",)),)
    )


def test_a_linter_config_bylaw_cannot_read_stays_prose_with_a_note() -> None:
    source = FakeSource(base={"ruff.toml": "[lint\nselect = ['S']\n"})

    rules, notes = collect_rules(_changed("app.py"), source, [])

    assert [(r.path, r.linter) for r in rules] == [("ruff.toml", None)]
    assert len(notes) == 1
    assert notes[0].startswith("ruff.toml: not valid TOML")
    assert notes[0].endswith("a finding cannot cite its rule ids.")
