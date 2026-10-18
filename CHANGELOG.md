# Changelog

All notable changes are listed here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow [Semantic Versioning](https://semver.org/).

## Unreleased

## 0.2.0 - 2026-10-18

- Incremental review: on a new push, the model sees only the files whose change differs from the last run, and the unchanged files keep their earlier findings. A criterion that was met stays met while the files it was met in are unchanged. `incremental = false` in `.bylaw.toml` turns it off (ADR 0012).
- A token budget per pull request: `[budget] pr_tokens` in `.bylaw.toml`. Once a pull request has used it, bylaw's own checks still run and the earlier model review stands.
- The summary's footer gives the model tokens of the run and of the pull request.
- When the model review does not run (no key, an error, or the budget), the earlier model findings stand instead of being resolved as fixed.
- The Claude Code and Codex plugin moved to `plugin/`, so plugin directories scan only the files users install. The skill now always runs the bylaw release from PyPI that it names. Existing installs pick up the new path from the marketplace on their next update.
- A moved file that GitHub sends without a blob sha, and whose old path is missing from the base, now gets the binary file note instead of counting as an unchanged move.
- A GraphQL error while reading the older replies of a long review thread no longer ends the run. The thread is read without them and the summary says so. A rate limit still stops the run.
- Validation keeps two different problems of the same category on the same lines, such as a shell injection and a path traversal on one line. Only a finding with the same message as another is dropped as a duplicate.
- Monorepos: a package's own `AGENTS.md`, `CLAUDE.md`, `CONTRIBUTING.md` and linter configuration now apply to the files changed under it, next to the root rules. For each changed file and each of those names, the nearest one above it on the base branch is read; directories without changed files are not read (ADR 0013).

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
