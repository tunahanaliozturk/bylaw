# Changelog

All notable changes are listed here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow [Semantic Versioning](https://semver.org/).

## Unreleased

- Changes are checked against accepted ADRs. The brief has a `decisions` block with each accepted ADR's title, status and decision section, numbered with the file's own lines, newest first and capped at 2,000 characters per ADR and 12,000 in all; the summary notes what was cut or left out and lists the ADRs among the rule sources. A change that goes against a decision gets a `rule` finding citing `docs/adr/<file>.md:<line>`, and validation keeps the citation only for a line the reviewer was shown. A changed ADR on the base branch forces a full review (ADR 0016).
- ADRs are read as decisions, not specs. `adr_globs` in `.bylaw.toml` (default `docs/adr/**` and `docs/decisions/**`) says where they live; bylaw reads the newest 40 from the base branch and keeps the accepted ones, whether the status is a `Status:` line, a `## Status` section or MADR front matter. `docs/adr/**` left the default `spec_globs`, and a file matching `adr_globs` is never a requirement, even when an older configuration still lists it as a spec, so an ADR is not counted twice (ADR 0016).
- Jira Cloud issues as requirements. A pull request that names an issue such as `PROJ-123` in its title, body or commits gets that issue's acceptance criteria in its summary, from a checklist or an "Acceptance criteria" section in the description or from a criteria field you name. It is an opt-in: a `[jira]` table in `.bylaw.toml` with the site and the allowed projects, and `JIRA_EMAIL` with `JIRA_API_TOKEN` in the environment (the Action's `jira-email` and `jira-api-token` inputs).
- Azure Boards work items as requirements. `AB#123` in a pull request's title, body or commits brings in that work item's title, description and Acceptance Criteria field. It needs an `[azure_boards]` table in `.bylaw.toml` with the organisation and the allowed projects, and `AZURE_DEVOPS_TOKEN` (the Action's `azure-devops-token` input). A work item in a project that is not listed is left out.
- Linear issues as requirements. An identifier such as `ENG-42` from a team listed under `[linear] teams` brings in that issue's title and Markdown description, with `LINEAR_API_KEY` in the environment (the Action's `linear-api-key` input). Only keys of listed projects and teams count as references, so `UTF-8` or `SHA-256` in a description never does.
- `quote_trackers = false` in `.bylaw.toml` keeps work item text out of the summary comment: for Jira, Azure Boards and Linear requirements it shows only the criterion keys, their status and where they are met, so a public pull request does not quote a private tracker (ADR 0014).
- Setup for each tracker, the Action inputs and what a left-out work item's note means: [docs/trackers.md](docs/trackers.md).
- Work items are read only for pull requests by owners, members and collaborators; for anyone else a note says they were not read. `trackers_for_all_authors = true` reads them for every author. The brief marks a work item kept out of quotes `Quotable: no` and tells the reviewer to name it by its labels only (ADR 0014).
- Tracker text keeps its criteria in more shapes: a code block at the start of a Jira list item no longer hides the criteria after it, HTML `<pre>` blocks and code fences in a criteria field are not read as criteria, table rows read as one line so a Given/When/Then table is a scenario, and a list item continued after a line break or a second paragraph stays one criterion.
- Keys in HTML comments, such as a pull request template's examples, are not work item references, and only ASCII digits make a key.
- A work item that does not exist and one outside the allow list get the same note, so notes do not reveal which keys exist elsewhere. A tracker token an HTTP header cannot carry is a note instead of a failed run.
- A `.bylaw.toml` error never repeats the rejected value, so a token pasted into the file stays out of the log; the message says to rotate it.
- Quoted prose in comments cannot mention people: a zero-width space follows every `@` in text from issues, work items, specs and the model. Code spans are left as written.

## 0.3.0 - 2026-10-18

- Monorepos: a package's own `AGENTS.md`, `CLAUDE.md`, `CONTRIBUTING.md` and linter configuration now apply to the files changed under it, next to the root rules. For each changed file and each of those names, the nearest one above it on the base branch is read; directories without changed files are not read. Ruff's `.ruff.toml`, `ruff.toml` and `pyproject.toml` count as one name, in Ruff's order. `.github/CONTRIBUTING.md` and `docs/CONTRIBUTING.md` stay rules for the whole repository. The brief groups the rules by directory, names the changed files each group covers, and tells the reviewer that the nearest directory wins (ADR 0013).
- Validation accepts a rule line from a package's own rule files as evidence, and drops a finding that cites a rule of another package than the file it is on.
- Linter configuration is read as rule ids, without running anything: Ruff's selected and ignored codes and per-file ignores (`ruff.toml`, `.ruff.toml`, `pyproject.toml`), following `extend` on the base branch, ESLint rules and overrides from `.eslintrc.json` and `.eslintrc.yml`, golangci-lint's enabled linters (v1 and v2 files), and .NET `dotnet_diagnostic` severities from `.editorconfig` and `.globalconfig`. What names no ids, such as an ESLint `extends`, a golangci-lint preset, a .NET category severity or the analysis level, is noted in the brief. ESLint configs written in JavaScript stay text. A file that does not parse is noted in the summary. YAML is read with `ruamel.yaml`'s safe loader, a new dependency.
- A finding can cite a linter rule id as evidence, written `<tool>:<id>` (`ruff:S608`, `eslint:no-console`, `golangci-lint:gosec`, `dotnet:CA2100`). The brief lists the ids each configuration enables. Validation drops a finding whose id the configuration governing its file turns off, or does not turn on when bylaw read all of that configuration; under an `extends` or another setting bylaw could not read, an unlisted id is kept. Only configurations for the file's language count, and for Ruff only the nearest one.
- The evaluation set has 55 cases: five new ones in `py-mono`, a monorepo whose two packages have conflicting `AGENTS.md` rules and their own Ruff configurations, two of them labelled with a rule id citation.

## 0.2.0 - 2026-10-18

- Incremental review: on a new push, the model sees only the files whose change differs from the last run, and the unchanged files keep their earlier findings. A criterion that was met stays met while the files it was met in are unchanged. `incremental = false` in `.bylaw.toml` turns it off (ADR 0012).
- A token budget per pull request: `[budget] pr_tokens` in `.bylaw.toml`. Once a pull request has used it, bylaw's own checks still run and the earlier model review stands.
- The summary's footer gives the model tokens of the run and of the pull request.
- When the model review does not run (no key, an error, or the budget), the earlier model findings stand instead of being resolved as fixed.
- The Claude Code and Codex plugin moved to `plugin/`, so plugin directories scan only the files users install. The skill now always runs the bylaw release from PyPI that it names. Existing installs pick up the new path from the marketplace on their next update.
- A moved file that GitHub sends without a blob sha, and whose old path is missing from the base, now gets the binary file note instead of counting as an unchanged move.
- A GraphQL error while reading the older replies of a long review thread no longer ends the run. The thread is read without them and the summary says so. A rate limit still stops the run.
- Validation keeps two different problems of the same category on the same lines, such as a shell injection and a path traversal on one line. Only a finding with the same message as another is dropped as a duplicate.

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
