from bylaw.editorconfig import Property
from bylaw.editorconfig_checks import check
from bylaw.model import AddedLine, Category, ChangedFile, Severity


def _file(*lines: str, missing_newline: bool = False, status: str = "modified") -> ChangedFile:
    return ChangedFile.model_validate(
        {
            "path": "src/app.py",
            "status": status,
            "added_lines": [AddedLine(number=n, text=t) for n, t in enumerate(lines, start=10)],
            "missing_final_newline": missing_newline,
        }
    )


def _props(**values: str) -> dict[str, Property]:
    return {
        key: Property(value, ".editorconfig", line) for line, (key, value) in enumerate(values.items(), 3)
    }


def test_tab_indent_under_space_style_is_one_finding_with_evidence() -> None:
    findings = check(_file("ok = 1", "\tx = 1", "\ty = 2"), _props(indent_style="space"))

    assert len(findings) == 1
    finding = findings[0]
    assert (finding.line_start, finding.category, finding.severity) == (11, Category.RULE, Severity.LOW)
    assert finding.evidence == ".editorconfig:3"
    assert "2 added lines, first at line 11" in finding.message


def test_space_indent_under_tab_style_uses_indent_size() -> None:
    findings = check(_file("  two", "    four"), _props(indent_style="tab", indent_size="4"))

    assert [f.line_start for f in findings] == [11]


def test_a_carriage_return_is_not_trailing_whitespace_or_length() -> None:
    findings = check(_file("x = 1\r"), _props(trim_trailing_whitespace="true", max_line_length="5"))

    assert findings == ()


def test_a_carriage_return_breaks_an_lf_rule() -> None:
    findings = check(_file("x = 1\r"), _props(end_of_line="lf"))

    assert [f.evidence for f in findings] == [".editorconfig:3"]


def test_trailing_whitespace_and_long_lines_are_reported() -> None:
    findings = check(
        _file("x = 1  ", "y" * 12), _props(trim_trailing_whitespace="true", max_line_length="10")
    )

    assert [(f.line_start, f.evidence) for f in findings] == [
        (10, ".editorconfig:3"),
        (11, ".editorconfig:4"),
    ]


def test_max_line_length_off_is_ignored() -> None:
    assert check(_file("y" * 500), _props(max_line_length="off")) == ()


def test_a_missing_final_newline_is_reported_on_the_last_added_line() -> None:
    findings = check(_file("a", "b", missing_newline=True), _props(insert_final_newline="true"))

    assert [(f.line_start, f.evidence) for f in findings] == [(11, ".editorconfig:3")]


def test_removed_files_are_not_checked() -> None:
    assert check(_file("\tx", status="removed"), _props(indent_style="space")) == ()
