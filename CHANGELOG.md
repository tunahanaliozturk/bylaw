# Changelog

All notable changes are listed here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow [Semantic Versioning](https://semver.org/).

## Unreleased

- The Claude Code and Codex plugin moved to `plugin/`, so plugin directories scan only the files users install. The skill now always runs the bylaw release from PyPI that it names. Existing installs pick up the new path from the marketplace on their next update.
- A moved file that GitHub sends without a blob sha, and whose old path is missing from the base, now gets the binary file note instead of counting as an unchanged move.

## 0.1.1 - 2026-10-16

- The PyPI page shows the README with its images, and links to the repository, issues and changelog.

## 0.1.0 - 2026-10-16

First release.

### Added

- Context collection for a pull request or a local branch: diff, rules from the base branch (`.editorconfig`, linter configs, `CONTRIBUTING.md`, `AGENTS.md`), issues the change closes and specs it links, with their acceptance criteria.
- Deterministic `.editorconfig` checks.
- Model review through Anthropic or OpenAI with a strict output schema, and validation of every finding before posting.
- Inline comments and one summary comment with the requirement checklist; re-runs update instead of repeating, and resolve fixed threads.
- GitHub Action, with recipes for `pull_request` and `pull_request_target`.
- Claude Code and Codex plugins sharing one skill, so the host model reviews without an API key.
- Inferred acceptance criteria for issues and specs written as prose, and maintainers' issue comments as part of the requirement.
- `bylaw eval`: 50 labelled pull requests in four languages, a resumable runner and a scorer.
