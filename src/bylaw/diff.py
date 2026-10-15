"""Parses unified diffs into the lines a pull request adds, numbered as they appear in the new file."""

import re

from bylaw.model import AddedLine, ChangedFile, FileStatus

_HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")
_GIT_HEADER = re.compile(r"^a/(?P<old>.+) b/(?P<new>.+)$")


def parse_patch(patch: str) -> tuple[tuple[AddedLine, ...], bool]:
    """Return the added lines and whether the new file ends without a newline.

    Lines are split on "\\n" only, so a "\\r" from a CRLF file stays in the text for the end_of_line check.
    """
    added: list[AddedLine] = []
    new_line = 0
    last_was_added = False
    missing_newline = False
    for raw in patch.split("\n"):
        if hunk := _HUNK.match(raw):
            new_line = int(hunk.group(1))
            last_was_added = False
        elif raw.startswith("\\"):
            # "\ No newline at end of file" describes the line just above it.
            missing_newline = missing_newline or last_was_added
        elif raw.startswith("+"):
            added.append(AddedLine(number=new_line, text=raw[1:]))
            new_line += 1
            last_was_added = True
        elif raw.startswith("-"):
            last_was_added = False
        else:
            new_line += 1
            last_was_added = False
    return tuple(added), missing_newline


def parse_unified_diff(text: str) -> tuple[ChangedFile, ...]:
    """Parse `git diff` output. Binary files and mode-only changes have no added lines."""
    files: list[ChangedFile] = []
    for block in re.split(r"(?m)^diff --git ", text)[1:]:
        header, marker, body = block.partition("\n@@")
        lines = header.split("\n")
        status: FileStatus = "modified"
        old_path: str | None = None
        new_path: str | None = None
        binary = False
        if names := _GIT_HEADER.match(lines[0]):
            old_path, new_path = names["old"], names["new"]
        for line in lines[1:]:
            if line.startswith("new file mode"):
                status = "added"
            elif line.startswith("deleted file mode"):
                status = "removed"
            elif line.startswith("rename from "):
                old_path = line.removeprefix("rename from ")
                status = "renamed"
            elif line.startswith("rename to "):
                new_path = line.removeprefix("rename to ")
            elif line.startswith("--- a/"):
                old_path = line.removeprefix("--- a/")
            elif line.startswith("+++ b/"):
                new_path = line.removeprefix("+++ b/")
            elif line.startswith("Binary files"):
                binary = True
        path = old_path if status == "removed" else new_path
        if path is None:
            continue
        added, missing = parse_patch("@@" + body) if marker else ((), False)
        files.append(
            ChangedFile(
                path=path,
                status=status,
                previous_path=old_path if status == "renamed" else None,
                added_lines=added,
                missing_final_newline=missing,
                patch_omitted=binary,
            )
        )
    return tuple(files)
