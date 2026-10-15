from bylaw.model import ChangedFile, RuleKind
from bylaw.rules import RULE_PATHS, collect_rules


def _changed(*paths: str) -> list[ChangedFile]:
    return [ChangedFile(path=p, status="modified") for p in paths]


def test_prose_rules_that_exist_on_the_base_are_collected() -> None:
    base = {"CONTRIBUTING.md": "Use parameterised queries.", "AGENTS.md": "Run the tests."}

    rules = collect_rules(_changed("README.md"), base.get, [])

    assert [(r.path, r.kind) for r in rules] == [
        ("CONTRIBUTING.md", RuleKind.PROSE),
        ("AGENTS.md", RuleKind.PROSE),
    ]


def test_linter_configuration_follows_the_languages_in_the_diff() -> None:
    base = {"ruff.toml": "line-length = 100", ".golangci.yml": "linters: {}"}

    python_rules = collect_rules(_changed("app.py"), base.get, [])
    docs_rules = collect_rules(_changed("README.md"), base.get, [])

    assert [r.path for r in python_rules] == ["ruff.toml"]
    assert docs_rules == ()


def test_pyproject_counts_only_when_it_configures_ruff() -> None:
    with_ruff = {"pyproject.toml": "[project]\n[tool.ruff]\nline-length = 100\n"}
    without_ruff = {"pyproject.toml": "[project]\nname = 'x'\n"}

    assert [r.path for r in collect_rules(_changed("a.py"), with_ruff.get, [])] == ["pyproject.toml"]
    assert collect_rules(_changed("a.py"), without_ruff.get, []) == ()


def test_editorconfig_files_already_read_are_passed_through_first() -> None:
    rules = collect_rules(_changed("a.py"), dict[str, str]().get, [(".editorconfig", "root = true")])

    assert [(r.path, r.kind) for r in rules] == [(".editorconfig", RuleKind.EDITORCONFIG)]


def test_rule_paths_include_the_bylaw_config_but_not_pyproject() -> None:
    assert ".bylaw.toml" in RULE_PATHS
    assert "CONTRIBUTING.md" in RULE_PATHS
    assert "pyproject.toml" not in RULE_PATHS
