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
