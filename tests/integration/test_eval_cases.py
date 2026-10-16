from pathlib import Path

import pytest

from bylaw.evaluation.cases import build_case_context, load_cases
from bylaw.model import Category


def _write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


@pytest.fixture
def root(tmp_path: Path) -> Path:
    _write(tmp_path / "projects/p/.editorconfig", b"root = true\n[*.py]\nindent_style = space\n")
    _write(tmp_path / "projects/p/app.py", b"def run():\n    return 1\n")
    _write(
        tmp_path / "cases/tabs/case.toml",
        b'project = "p"\nkind = "rule"\ntitle = "Tabs"\nmessage = "Use tabs"\n\n'
        b'[[findings]]\nfile = "app.py"\nlines = [2, 2]\ncategories = ["rule"]\n'
        b'note = "tab indent"\ndeterministic = true\n',
    )
    _write(tmp_path / "cases/tabs/head/app.py", b"def run():\n\treturn 2\n")
    return tmp_path


def test_a_case_loads_with_its_directory_name_as_id(root: Path) -> None:
    (case,) = load_cases(root)

    assert case.id == "tabs"
    assert case.findings[0].categories == (Category.RULE,)
    assert case.findings[0].lines == (2, 2)


def test_a_case_builds_into_the_context_a_pull_request_would_have(root: Path, tmp_path: Path) -> None:
    (case,) = load_cases(root)

    context = build_case_context(root, case, tmp_path / "work")

    assert context.title == "Tabs"
    assert [f.path for f in context.files] == ["app.py"]
    assert [(f.file, f.line_start, f.evidence) for f in context.findings] == [
        ("app.py", 2, ".editorconfig:3")
    ]


def test_a_typo_in_a_case_file_fails_and_names_the_case(root: Path) -> None:
    toml = root / "cases/tabs/case.toml"
    toml.write_bytes(toml.read_bytes().replace(b"categories", b"catgories"))

    with pytest.raises(ValueError, match="tabs"):
        load_cases(root)


def test_a_case_directory_without_case_toml_is_an_error(root: Path) -> None:
    (root / "cases/forgotten").mkdir()

    with pytest.raises(ValueError, match="forgotten"):
        load_cases(root)


@pytest.mark.parametrize(
    ("kind", "labels"),
    [
        ("security", ""),
        ("clean", '[[findings]]\nfile = "a.py"\nlines = [1, 1]\ncategories = ["bug"]\nnote = "n"\n'),
    ],
)
def test_a_kind_that_does_not_match_the_labels_is_an_error(root: Path, kind: str, labels: str) -> None:
    case = root / "cases/odd"
    case.mkdir()
    (case / "case.toml").write_text(
        f'project = "p"\nkind = "{kind}"\ntitle = "t"\nmessage = "m"\n{labels}', "utf-8"
    )

    with pytest.raises(ValueError, match="odd"):
        load_cases(root)


def test_global_git_hooks_do_not_run_in_case_repositories(
    root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    hooks = tmp_path / "hooks"
    hooks.mkdir()
    (hooks / "pre-commit").write_bytes(b"#!/bin/sh\nexit 1\n")
    (hooks / "pre-commit").chmod(0o755)
    config = tmp_path / "gitconfig"
    config.write_text(f"[core]\n\thooksPath = {hooks.as_posix()}\n", encoding="utf-8")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(config))
    (case,) = load_cases(root)

    context = build_case_context(root, case, tmp_path / "work")

    assert [f.path for f in context.files] == ["app.py"]
