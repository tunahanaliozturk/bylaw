from bylaw.editorconfig import EditorConfigResolver, Property


def _resolver(files: dict[str, str]) -> EditorConfigResolver:
    return EditorConfigResolver(files.get)


def test_a_pattern_without_a_slash_matches_at_any_depth() -> None:
    resolver = _resolver({".editorconfig": "root = true\n[*.py]\nindent_style = space\n"})

    assert resolver.properties("src/pkg/mod.py")["indent_style"].value == "space"


def test_a_leading_slash_anchors_the_pattern_to_the_config_directory() -> None:
    resolver = _resolver({".editorconfig": "[/src/*.py]\nindent_size = 2\n"})

    assert "indent_size" in resolver.properties("src/a.py")
    assert "indent_size" not in resolver.properties("src/sub/a.py")
    assert "indent_size" not in resolver.properties("lib/src/a.py")


def test_braces_match_any_listed_alternative() -> None:
    resolver = _resolver({".editorconfig": "[*.{js,ts}]\nindent_size = 2\n"})

    assert "indent_size" in resolver.properties("web/app.ts")
    assert "indent_size" not in resolver.properties("web/app.py")


def test_a_numeric_range_matches_only_numbers_inside_it() -> None:
    resolver = _resolver({".editorconfig": "[file{1..3}.txt]\nindent_size = 2\n"})

    assert "indent_size" in resolver.properties("file2.txt")
    assert "indent_size" not in resolver.properties("file4.txt")


def test_a_negated_class_excludes_its_characters() -> None:
    resolver = _resolver({".editorconfig": "[[!a]bc.txt]\nindent_size = 2\n"})

    assert "indent_size" in resolver.properties("xbc.txt")
    assert "indent_size" not in resolver.properties("abc.txt")


def test_a_closer_file_overrides_a_parent_and_names_itself_as_the_source() -> None:
    resolver = _resolver(
        {
            ".editorconfig": "root = true\n[*]\nindent_size = 2\n",
            "src/.editorconfig": "[*]\nindent_size = 4\n",
        }
    )

    assert resolver.properties("src/a.py")["indent_size"] == Property("4", "src/.editorconfig", 2)


def test_root_true_stops_the_search_for_parent_files() -> None:
    resolver = _resolver(
        {
            ".editorconfig": "[*]\nmax_line_length = 80\n",
            "src/.editorconfig": "root = true\n[*]\nindent_size = 4\n",
        }
    )

    assert "max_line_length" not in resolver.properties("src/a.py")


def test_a_later_section_wins_and_its_line_is_the_evidence() -> None:
    resolver = _resolver({".editorconfig": "[*]\nindent_style = tab\n\n[*.py]\nindent_style = Space\n"})

    assert resolver.properties("a.py")["indent_style"] == Property("space", ".editorconfig", 5)


def test_only_files_that_exist_are_reported_as_read() -> None:
    resolver = _resolver({".editorconfig": "[*]\nindent_size = 2\n"})
    resolver.properties("src/deep/a.py")

    assert resolver.files_read == ((".editorconfig", "[*]\nindent_size = 2\n"),)


def test_a_byte_order_mark_does_not_hide_the_first_line() -> None:
    resolver = _resolver(
        {
            ".editorconfig": "\ufeffroot = true\n[*]\nindent_size = 2\n",
            "src/.editorconfig": "\ufeff[*]\nmax_line_length = 80\n",
        }
    )

    properties = resolver.properties("src/a.py")

    assert properties["max_line_length"].value == "80"
    assert properties["indent_size"].value == "2"
