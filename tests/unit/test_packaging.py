"""The plugin files other tools read: they must parse, agree on name and version, and name real commands."""

import argparse
import json
import re
import tomllib
from pathlib import Path
from typing import cast

from bylaw.cli import _parser

ROOT = Path(__file__).resolve().parents[2]
SKILL = ROOT / "skills" / "bylaw-review" / "SKILL.md"


def _json(path: str) -> dict[str, object]:
    data = json.loads((ROOT / path).read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


def _project_version() -> str:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    return str(project["version"])


def test_both_plugin_manifests_carry_the_project_name_and_version() -> None:
    for path in (".claude-plugin/plugin.json", ".codex-plugin/plugin.json"):
        manifest = _json(path)
        assert (manifest["name"], manifest["version"]) == ("bylaw", _project_version()), path


def test_both_marketplaces_list_the_plugin_at_the_repository_root() -> None:
    claude = _json(".claude-plugin/marketplace.json")
    codex = _json(".agents/plugins/marketplace.json")

    assert claude["name"] == codex["name"] == "bylaw"
    assert claude["plugins"] == [
        {"name": "bylaw", "source": ".", "description": claude["plugins"][0]["description"]}  # type: ignore[index]
    ]
    assert codex["plugins"][0]["name"] == "bylaw"  # type: ignore[index]
    assert codex["plugins"][0]["source"] == {"source": "local", "path": "./"}  # type: ignore[index]


def test_the_skill_has_the_frontmatter_both_hosts_read() -> None:
    text = SKILL.read_text(encoding="utf-8")
    front = text.split("---", 2)[1]

    assert re.search(r"^name: bylaw-review$", front, re.MULTILINE)
    description = re.search(r"^description: (.+)$", front, re.MULTILINE)
    assert description is not None
    assert 40 < len(description.group(1)) < 1024


def test_every_bylaw_command_and_flag_the_skill_mentions_exists() -> None:
    command_file = ROOT / "commands" / "bylaw-review.md"
    text = SKILL.read_text(encoding="utf-8") + command_file.read_text(encoding="utf-8")
    action = _parser()._subparsers._group_actions[0]  # type: ignore[union-attr]
    subcommands = cast(dict[str, argparse.ArgumentParser], action.choices)

    uses = re.findall(r"\bbylaw (context|prompt|schema|validate|post|review)\b([^`\n]*)", text)
    assert uses
    for command, rest in uses:
        assert command in subcommands, command
        for flag in re.findall(r"(--[a-z][a-z-]+)", rest):
            assert flag in subcommands[command].format_help(), f"bylaw {command} {flag}"


def test_the_skill_runs_the_bylaw_that_ships_with_it_not_the_tip_of_main() -> None:
    text = SKILL.read_text(encoding="utf-8")

    assert "uvx --from <plugin root> bylaw" in text
    assert "two levels above this SKILL.md" in text


def test_the_skill_writes_files_through_bylaw_not_a_shell_redirect() -> None:
    # A redirect on Windows PowerShell re-encodes the file, and $TMP is unset on macOS and Linux.
    text = SKILL.read_text(encoding="utf-8")

    assert " > " not in text
    assert "$TMP" not in text
    assert "--output <work>/context.json" in text
    assert "--output <work>/brief.txt" in text


def test_the_skill_passes_the_token_inline_and_never_prints_it() -> None:
    text = SKILL.read_text(encoding="utf-8")

    assert "GITHUB_TOKEN=$(gh auth token)" in text
    assert "$env:GITHUB_TOKEN = gh auth token" in text
    assert "Never print the token" in text


def test_the_fork_recipe_runs_only_for_its_own_label() -> None:
    # Another label added to an approved pull request must not start a paid review again.
    recipe = (ROOT / "docs" / "recipes" / "pull-request-target.yml").read_text(encoding="utf-8")

    assert "github.event.action != 'labeled' || github.event.label.name == 'bylaw'" in recipe


def test_the_codex_manifest_is_ready_for_a_listing() -> None:
    interface = _json(".codex-plugin/plugin.json")["interface"]
    assert isinstance(interface, dict)

    for field in ("websiteURL", "privacyPolicyURL", "termsOfServiceURL", "longDescription", "brandColor"):
        assert interface.get(field), field
    for field in ("logo", "composerIcon"):
        path = interface[field]
        assert path.startswith("./assets/") and (ROOT / path).is_file(), field
    assert interface["capabilities"] == ["Read", "Write"]
    assert not any(re.search(r"\d", prompt) for prompt in interface["defaultPrompt"])


def test_the_command_finds_the_repository_and_default_branch_from_github_not_origin() -> None:
    text = (ROOT / "commands" / "bylaw-review.md").read_text(encoding="utf-8")

    assert "gh repo view --json nameWithOwner,defaultBranchRef" in text
    assert "git remote get-url origin" not in text
    assert "#12" in text and "pull request URL" in text
    assert "`post` alone" in text


def test_the_skill_warns_about_uncommitted_work_and_a_stale_checkout() -> None:
    text = SKILL.read_text(encoding="utf-8")

    assert "git status --porcelain" in text
    assert "is not the pull request's head" in text
