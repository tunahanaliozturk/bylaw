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
