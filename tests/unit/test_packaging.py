"""The plugin files other tools read: they must parse, agree on name and version, and name real commands."""

import argparse
import json
import re
import subprocess
import sys
import tomllib
from pathlib import Path
from typing import cast

from ruamel.yaml import YAML

from bylaw.cli import _parser

ROOT = Path(__file__).resolve().parents[2]
# The plugin lives in its own folder so the plugin directories scan only what users install.
PLUGIN = ROOT / "plugin"
SKILL = PLUGIN / "skills" / "bylaw-review" / "SKILL.md"
COMMAND = PLUGIN / "commands" / "bylaw-review.md"


def _json(path: str) -> dict[str, object]:
    data = json.loads((ROOT / path).read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


def _project_version() -> str:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    return str(project["version"])


def test_both_plugin_manifests_carry_the_project_name_and_version() -> None:
    for path in ("plugin/.claude-plugin/plugin.json", "plugin/plugin.json"):
        manifest = _json(path)
        assert (manifest["name"], manifest["version"]) == ("bylaw", _project_version()), path


def test_both_marketplaces_list_the_plugin_folder() -> None:
    claude = _json(".claude-plugin/marketplace.json")
    codex = _json(".agents/plugins/marketplace.json")

    assert claude["name"] == codex["name"] == "bylaw"
    assert claude["plugins"] == [
        {"name": "bylaw", "source": "./plugin", "description": claude["plugins"][0]["description"]}  # type: ignore[index]
    ]
    assert codex["plugins"][0]["name"] == "bylaw"  # type: ignore[index]
    assert codex["plugins"][0]["source"] == {"source": "local", "path": "./plugin"}  # type: ignore[index]
    assert not (ROOT / ".claude-plugin" / "plugin.json").exists()
    assert not (ROOT / "plugin.json").exists()


def test_the_plugin_folder_holds_only_what_users_install() -> None:
    # The Claude directory reads the whole plugin folder and holds it for review over credentials beside URLs,
    # file names of images, and download commands. Keep it to the plugin itself.
    files = sorted(p.relative_to(PLUGIN).as_posix() for p in PLUGIN.rglob("*") if p.is_file())
    assert files == [
        ".claude-plugin/plugin.json",
        "LICENSE",
        "README.md",
        "assets/icon.png",
        "assets/logo.png",
        "commands/bylaw-review.md",
        "plugin.json",
        "skills/bylaw-review/SKILL.md",
    ]
    readme = (PLUGIN / "README.md").read_text(encoding="utf-8")
    assert len(readme.split()) >= 40
    for path in ("README.md", "commands/bylaw-review.md", "skills/bylaw-review/SKILL.md"):
        assert "://" not in (PLUGIN / path).read_text(encoding="utf-8"), path


def test_the_skill_has_the_frontmatter_both_hosts_read() -> None:
    text = SKILL.read_text(encoding="utf-8")
    front = text.split("---", 2)[1]

    assert re.search(r"^name: bylaw-review$", front, re.MULTILINE)
    description = re.search(r"^description: (.+)$", front, re.MULTILINE)
    assert description is not None
    assert 40 < len(description.group(1)) < 1024


def test_every_bylaw_command_and_flag_the_skill_mentions_exists() -> None:
    text = SKILL.read_text(encoding="utf-8") + COMMAND.read_text(encoding="utf-8")
    action = _parser()._subparsers._group_actions[0]  # type: ignore[union-attr]
    subcommands = cast(dict[str, argparse.ArgumentParser], action.choices)

    uses = re.findall(r"\bbylaw (context|prompt|schema|validate|post|review)\b([^`\n]*)", text)
    assert uses
    for command, rest in uses:
        assert command in subcommands, command
        for flag in re.findall(r"(--[a-z][a-z-]+)", rest):
            assert flag in subcommands[command].format_help(), f"bylaw {command} {flag}"


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
    # The portable root manifest carries Codex settings under extensions."com.openai" (Codex plugin docs).
    interface = _json("plugin/plugin.json")["extensions"]["com.openai"]["interface"]  # type: ignore[index]
    assert not (ROOT / ".codex-plugin").exists()
    assert isinstance(interface, dict)

    for field in ("websiteURL", "privacyPolicyURL", "termsOfServiceURL", "longDescription", "brandColor"):
        assert interface.get(field), field
    for field in ("logo", "composerIcon"):
        path = interface[field]
        assert path.startswith("./assets/") and (PLUGIN / path).is_file(), field
    assert interface["capabilities"] == ["Read", "Write"]
    assert not any(re.search(r"\d", prompt) for prompt in interface["defaultPrompt"])


def test_the_command_finds_the_repository_and_default_branch_from_github_not_origin() -> None:
    text = COMMAND.read_text(encoding="utf-8")

    assert "gh repo view --json nameWithOwner,defaultBranchRef,isFork,parent" in text
    assert "`parent`" in text
    assert "git remote get-url origin" not in text
    assert "#12" in text and "pull request URL" in text
    assert "`post` alone" in text


def test_the_skill_warns_about_uncommitted_work_and_a_stale_checkout() -> None:
    text = SKILL.read_text(encoding="utf-8")

    assert "git status --porcelain" in text
    assert "is not the pull request's head" in text


def test_a_skipped_fork_run_cannot_cancel_a_running_review() -> None:
    # Concurrency at workflow level would let a run for another label cancel the review, then skip itself.
    recipe = (ROOT / "docs" / "recipes" / "pull-request-target.yml").read_text(encoding="utf-8")

    assert recipe.index("concurrency:") > recipe.index("jobs:")


def test_the_skill_itself_says_how_to_find_the_repository_and_the_pull_request() -> None:
    # Codex loads only the skill, so the target steps cannot live in the Claude Code command alone.
    text = SKILL.read_text(encoding="utf-8")

    assert "gh repo view --json nameWithOwner,defaultBranchRef,isFork,parent" in text
    assert "gh pr view --json number" in text


def test_the_skill_runs_the_released_version_it_was_shipped_with() -> None:
    # The plugin folder carries no bylaw source, so the skill pins the PyPI release of the same version.
    text = SKILL.read_text(encoding="utf-8")

    assert f"uvx bylaw@{_project_version()}" in text
    assert "--from" not in text


def test_the_mcp_sdk_is_an_optional_extra_that_the_cli_never_imports() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    probe = "import sys, bylaw.cli; print(sorted(n for n in sys.modules if n.partition('.')[0] == 'mcp'))"

    done = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True, check=True)

    assert not [d for d in project["dependencies"] if d.startswith("mcp")]
    assert [d for d in project["optional-dependencies"]["mcp"] if d.startswith("mcp>=")]
    assert done.stdout.strip() == "[]"


def test_the_fork_recipe_never_cancels_a_review_in_progress() -> None:
    # A fork author who pushes again and again after the label would otherwise cancel each run before
    # its tokens reach the summary, so `[budget] pr_tokens` would never count them.
    recipe = (ROOT / "docs" / "recipes" / "pull-request-target.yml").read_text(encoding="utf-8")

    assert "cancel-in-progress: false" in recipe
    assert "cancel-in-progress: true" not in recipe
    assert "pr_tokens" in recipe


def test_the_learning_recipe_gives_write_access_to_contents_only_to_the_closing_job() -> None:
    # The review job reads the author's text and sends it to a model; it must not be able to push.
    text = (ROOT / "docs" / "learning.md").read_text(encoding="utf-8")
    block = text.split("```yaml\n", 1)[1].split("```", 1)[0]
    workflow = YAML(typ="safe").load(block)
    jobs = workflow["jobs"]

    assert workflow["permissions"] == {}
    assert jobs["review"]["if"] == "github.event.action != 'closed'"
    assert jobs["review"]["permissions"]["contents"] == "read"
    assert jobs["learn"]["if"] == "github.event.action == 'closed'"
    assert jobs["learn"]["permissions"]["contents"] == "write"


def test_the_gitlab_recipe_pins_its_image_by_digest_and_its_dependencies_by_date() -> None:
    job = YAML(typ="safe").load((ROOT / "docs" / "recipes" / "gitlab-ci.yml").read_text(encoding="utf-8"))
    image, cutoff = job["bylaw"]["image"], job["bylaw"]["variables"]["UV_EXCLUDE_NEWER"]

    assert re.fullmatch(r"ghcr\.io/astral-sh/uv:[\w.-]+@sha256:[0-9a-f]{64}", image)
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", cutoff)


def test_releases_are_built_with_the_hashed_build_backend() -> None:
    release = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    constraints = (ROOT / "tools" / "build-constraints.txt").read_text(encoding="utf-8")
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    required = project["build-system"]["requires"]

    assert "uv build --build-constraints tools/build-constraints.txt --require-hashes" in release
    pinned = re.search(r"^hatchling==([\d.]+) \\\n\s+--hash=sha256:", constraints, re.MULTILINE)
    assert pinned is not None
    floor = re.fullmatch(r"hatchling>=([\d.]+)", required[0])
    assert floor is not None
    assert tuple(map(int, pinned[1].split("."))) >= tuple(map(int, floor[1].split(".")))
