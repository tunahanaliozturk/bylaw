from pathlib import Path

from bylaw.app.secrets import DirectorySecrets, EnvSecrets


def test_environment_secrets_are_read_per_installation() -> None:
    environ = {
        "BYLAW_INSTALLATION_7_ANTHROPIC_API_KEY": "key-7",
        "BYLAW_INSTALLATION_7_JIRA_API_TOKEN": "jira-7",
        "BYLAW_INSTALLATION_8_ANTHROPIC_API_KEY": "key-8",
        "ANTHROPIC_API_KEY": "the server's own",
    }

    assert EnvSecrets(environ).secrets(7) == {"ANTHROPIC_API_KEY": "key-7", "JIRA_API_TOKEN": "jira-7"}
    assert EnvSecrets(environ).secrets(9) == {}


def test_only_the_names_bylaw_reads_are_taken() -> None:
    environ = {"BYLAW_INSTALLATION_7_GITHUB_TOKEN": "x", "BYLAW_INSTALLATION_7_PATH": "/bin"}

    assert EnvSecrets(environ).secrets(7) == {}


def test_an_empty_value_counts_as_no_secret() -> None:
    assert EnvSecrets({"BYLAW_INSTALLATION_7_OPENAI_API_KEY": ""}).secrets(7) == {}


def test_directory_secrets_are_one_file_per_name_in_a_folder_per_installation(tmp_path: Path) -> None:
    (tmp_path / "7").mkdir()
    (tmp_path / "7" / "ANTHROPIC_API_KEY").write_text("key-7\n", encoding="utf-8")
    (tmp_path / "7" / "LINEAR_API_KEY").write_text("  lin  ", encoding="utf-8")
    (tmp_path / "7" / "notes.txt").write_text("ignored", encoding="utf-8")
    (tmp_path / "8").mkdir()
    (tmp_path / "8" / "ANTHROPIC_API_KEY").write_text("key-8", encoding="utf-8")

    assert DirectorySecrets(tmp_path).secrets(7) == {"ANTHROPIC_API_KEY": "key-7", "LINEAR_API_KEY": "lin"}
    assert DirectorySecrets(tmp_path).secrets(9) == {}


def test_neither_store_shows_its_values_when_printed(tmp_path: Path) -> None:
    store = EnvSecrets({"BYLAW_INSTALLATION_7_ANTHROPIC_API_KEY": "sk-ant-secret"})

    assert "sk-ant-secret" not in repr(store)
    assert "sk-ant-secret" not in repr(DirectorySecrets(tmp_path))
