# Changelog

All notable changes are listed here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow [Semantic Versioning](https://semver.org/).

## Unreleased

### Added

- Context collection for a pull request or a local branch: diff, rules from the base branch (`.editorconfig`, linter configs, `CONTRIBUTING.md`, `AGENTS.md`), issues the change closes and specs it links, with their acceptance criteria.
- Deterministic `.editorconfig` checks.
- Model review through Anthropic or OpenAI with a strict output schema, and validation of every finding before posting.
- Inline comments and one summary comment with the requirement checklist; re-runs update instead of repeating, and resolve fixed threads.
- GitHub Action, with recipes for `pull_request` and `pull_request_target`.
- Claude Code and Codex plugins sharing one skill, so the host model reviews without an API key.
- `bylaw eval`: 50 labelled pull requests in four languages, a resumable runner and a scorer.
