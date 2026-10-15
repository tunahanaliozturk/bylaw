"""Checks added lines against .editorconfig without a model. These findings are exact and cost nothing."""

from collections.abc import Mapping

from bylaw.editorconfig import Property
from bylaw.model import Category, ChangedFile, Finding, Severity

_DEFAULT_INDENT = 4


def check(file: ChangedFile, properties: Mapping[str, Property]) -> tuple[Finding, ...]:
    if file.status == "removed" or file.patch_omitted or not file.added_lines:
        return ()
    lines = [(a.number, a.text.removesuffix("\r"), a.text.endswith("\r")) for a in file.added_lines]
    rules: list[tuple[str, list[int], str]] = []

    style = properties.get("indent_style")
    if style is not None and style.value == "space":
        tabbed = [n for n, text, _ in lines if "\t" in _indent(text)]
        rules.append(("indent_style", tabbed, "Indented with tabs where .editorconfig asks for spaces"))
    elif style is not None and style.value == "tab":
        spaces = " " * _indent_width(properties)
        spaced = [n for n, text, _ in lines if _indent(text).startswith(spaces)]
        rules.append(("indent_style", spaced, "Indented with spaces where .editorconfig asks for tabs"))

    if _is_true(properties, "trim_trailing_whitespace"):
        trailing = [n for n, text, _ in lines if text != text.rstrip(" \t")]
        rules.append(("trim_trailing_whitespace", trailing, "Trailing whitespace"))

    limit = properties.get("max_line_length")
    if limit is not None and limit.value.isdigit():
        long_lines = [n for n, text, _ in lines if len(text) > int(limit.value)]
        rules.append(("max_line_length", long_lines, f"Longer than {limit.value} characters"))

    # ponytail: only `lf` is checked. Repositories usually store LF and convert to CRLF on checkout, so a
    # `crlf` rule would flag every stored line. Revisit if a user stores CRLF on purpose.
    eol = properties.get("end_of_line")
    if eol is not None and eol.value == "lf":
        crlf = [n for n, _, has_cr in lines if has_cr]
        rules.append(("end_of_line", crlf, "CRLF line ending where .editorconfig asks for LF"))

    findings = [
        _finding(file.path, properties[name], numbers, text) for name, numbers, text in rules if numbers
    ]
    if file.missing_final_newline and _is_true(properties, "insert_final_newline"):
        last = file.added_lines[-1].number
        findings.append(
            _finding(
                file.path, properties["insert_final_newline"], [last], "No newline at the end of the file"
            )
        )
    return tuple(findings)


def _indent(text: str) -> str:
    return text[: len(text) - len(text.lstrip(" \t"))]


def _indent_width(properties: Mapping[str, Property]) -> int:
    for key in ("indent_size", "tab_width"):
        value = properties.get(key)
        if value is not None and value.value.isdigit():
            return int(value.value)
    return _DEFAULT_INDENT


def _is_true(properties: Mapping[str, Property], key: str) -> bool:
    value = properties.get(key)
    return value is not None and value.value == "true"


def _finding(path: str, prop: Property, numbers: list[int], text: str) -> Finding:
    first = numbers[0]
    where = (
        f"on line {first}" if len(numbers) == 1 else f"on {len(numbers)} added lines, first at line {first}"
    )
    return Finding(
        file=path,
        line_start=first,
        line_end=first,
        category=Category.RULE,
        severity=Severity.LOW,
        message=f"{text} {where}.",
        evidence=f"{prop.source}:{prop.line}",
    )
