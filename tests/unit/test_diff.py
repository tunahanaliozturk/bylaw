from bylaw.diff import parse_patch, parse_unified_diff

PATCH = "\n".join(
    [
        "@@ -1,3 +1,4 @@",
        " import os",
        "-import sys",
        "+import re",
        "+import json",
        " ",
        "@@ -10,2 +11,2 @@ def main():",
        "     run()",
        "-    exit()",
        "+    raise SystemExit",
        "\\ No newline at end of file",
    ]
)

DIFF = """diff --git a/src/app.py b/src/app.py
index 1111111..2222222 100644
--- a/src/app.py
+++ b/src/app.py
@@ -1 +1,2 @@
 a
+b
diff --git a/new.txt b/new.txt
new file mode 100644
index 0000000..3333333
--- /dev/null
+++ b/new.txt
@@ -0,0 +1 @@
+hello
diff --git a/gone.txt b/gone.txt
deleted file mode 100644
index 4444444..0000000
--- a/gone.txt
+++ /dev/null
@@ -1 +0,0 @@
-bye
diff --git a/old name.py b/new name.py
similarity index 90%
rename from old name.py
rename to new name.py
index 5555555..6666666 100644
--- a/old name.py
+++ b/new name.py
@@ -1 +1 @@
-x
+y
diff --git a/logo.png b/logo.png
new file mode 100644
index 0000000..7777777
Binary files /dev/null and b/logo.png differ
"""


def test_added_lines_carry_their_new_file_numbers_across_hunks() -> None:
    added, _ = parse_patch(PATCH)

    assert [(line.number, line.text) for line in added] == [
        (2, "import re"),
        (3, "import json"),
        (12, "    raise SystemExit"),
    ]


def test_a_missing_newline_after_an_added_line_is_reported() -> None:
    _, missing = parse_patch(PATCH)

    assert missing is True


def test_a_missing_newline_marker_after_a_removed_line_is_not_reported() -> None:
    _, missing = parse_patch("@@ -1 +1 @@\n-old\n\\ No newline at end of file\n+new\n")

    assert missing is False


def test_carriage_returns_are_kept_in_the_line_text() -> None:
    added, _ = parse_patch("@@ -0,0 +1 @@\n+x = 1\r\n")

    assert added[0].text == "x = 1\r"


def test_a_git_diff_yields_status_paths_and_added_lines_per_file() -> None:
    files = parse_unified_diff(DIFF)

    summary = [
        (f.path, f.status, f.previous_path, [a.number for a in f.added_lines], f.patch_omitted) for f in files
    ]
    assert summary == [
        ("src/app.py", "modified", None, [2], False),
        ("new.txt", "added", None, [1], False),
        ("gone.txt", "removed", None, [], False),
        ("new name.py", "renamed", "old name.py", [1], False),
        ("logo.png", "added", None, [], True),
    ]


def test_paths_with_spaces_lose_the_tab_git_appends() -> None:
    diff = (
        "diff --git a/sp ace.py b/sp ace.py\n"
        "index 1111111..2222222 100644\n"
        "--- a/sp ace.py\t\n"
        "+++ b/sp ace.py\t\n"
        "@@ -1 +1 @@\n"
        "-x\n"
        "+y\n"
    )

    assert [f.path for f in parse_unified_diff(diff)] == ["sp ace.py"]


def test_c_quoted_paths_are_unquoted() -> None:
    # git writes a backslash in a path as "\\" inside a C-quoted name.
    diff = (
        r'diff --git "a/back\\slash.py" "b/back\\slash.py"' + "\n"
        "index 1111111..2222222 100644\n"
        r'--- "a/back\\slash.py"' + "\n"
        r'+++ "b/back\\slash.py"' + "\n"
        "@@ -1 +1 @@\n"
        "-x\n"
        "+y\n"
    )

    assert [f.path for f in parse_unified_diff(diff)] == [r"back\slash.py"]
