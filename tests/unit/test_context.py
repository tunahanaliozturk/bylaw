import pytest

from bylaw.config import ConfigError, load_config
from bylaw.context import build_context, generated_patterns, is_skipped
from bylaw.model import AddedLine, ChangedFile, ReviewContext
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
    assert "Skipped 3 lock, vendored or generated file(s)." in context.notes


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
