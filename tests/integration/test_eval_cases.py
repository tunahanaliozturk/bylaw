import json
import socket
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


SNAPSHOT = {
    "repo": "octo/app",
    "number": 7,
    "url": "https://github.com/octo/app/pull/7",
    "licence": "MIT",
    "base_sha": "b" * 40,
    "head_sha": "h" * 40,
    "title": "Cap retries",
    "body": "Retries forever today.",
    "commit_messages": ["Cap retries\n\nFixes #3"],
    "closing": [{"owner": "octo", "repo": "app", "number": 3}],
    "issues": [
        {
            "owner": "octo",
            "repo": "app",
            "number": 3,
            "title": "Retries never stop",
            "body": "## Acceptance criteria\n\n- [ ] stop after 3 attempts\n",
        }
    ],
}


@pytest.fixture
def real(tmp_path: Path) -> Path:
    root = tmp_path / "real"
    case = root / "cases/octo-app-7"
    _write(case / "snapshot.json", json.dumps(SNAPSHOT).encode())
    _write(case / "LICENSE", b"MIT License\n")
    _write(case / "base/CONTRIBUTING.md", b"# Contributing\n\n- Log with the logger.\n")
    _write(case / "base/retry.py", b"def attempts():\n    return None\n")
    _write(case / "head/retry.py", b"def attempts():\n    return 4\n")
    _write(
        case / "case.toml",
        b'kind = "bug"\nlabellers = ["first pass (model)"]\n\n'
        b'[[findings]]\nfile = "retry.py"\nlines = [2, 2]\ncategories = ["bug"]\nnote = "four, not three"\n',
    )
    return root


def test_a_real_case_takes_its_title_from_the_snapshot_and_is_provisional(real: Path) -> None:
    (case,) = load_cases(real)

    assert (case.title, case.project) == ("Cap retries", "")
    assert case.pull_request is not None
    assert case.pull_request.url == "https://github.com/octo/app/pull/7"
    assert case.provisional


def test_two_people_make_a_real_case_final(real: Path) -> None:
    toml = real / "cases/octo-app-7/case.toml"
    toml.write_bytes(toml.read_bytes().replace(b'["first pass (model)"]', b'["ada", "grace"]'))

    (case,) = load_cases(real)

    assert not case.provisional


def test_a_real_case_with_no_labeller_is_an_error(real: Path) -> None:
    toml = real / "cases/octo-app-7/case.toml"
    toml.write_bytes(toml.read_bytes().replace(b'labellers = ["first pass (model)"]\n', b""))

    with pytest.raises(ValueError, match="names its labellers"):
        load_cases(real)


def test_a_disagreement_names_only_the_cases_labellers(real: Path) -> None:
    toml = real / "cases/octo-app-7/case.toml"
    toml.write_bytes(
        toml.read_bytes().replace(b'["first pass (model)"]', b'["ada", "grace"]')
        + b'\n[[disagreements]]\nabout = "retry.py:2"\nresolution = "bug"\n'
        b'views = { ada = "bug", linus = "fine" }\n'
    )

    with pytest.raises(ValueError, match="linus did not label"):
        load_cases(real)


def test_a_real_case_replays_the_frozen_pull_request_without_the_network(
    real: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def no_network(*_: object) -> None:
        raise AssertionError("a snapshot run opened a network connection")

    monkeypatch.setattr(socket.socket, "connect", no_network)
    (case,) = load_cases(real)

    context = build_case_context(real, case, tmp_path / "work")

    assert context.title == "Cap retries"
    assert [(f.path, [line.number for line in f.added_lines]) for f in context.files] == [("retry.py", [2])]
    assert [r.path for r in context.rules] == ["CONTRIBUTING.md"]
    (issue,) = context.requirements
    assert (issue.source, issue.title) == ("issue#3", "Retries never stop")
    assert [c.key for c in issue.criteria] == ["AC-1"]
