# bylaw design

Status: accepted, 2026-10-15. Decisions with lasting weight are recorded as ADRs in `docs/adr/`; this
document describes the whole system and links to them.

## What bylaw is

bylaw reviews a pull request against the repository's own written rules and the requirements the pull
request claims to implement, and posts the findings as review comments. It runs as a GitHub Action, as a
Claude Code plugin, and as a Codex skill, all built on one Python package.

Two things set it apart from a general purpose AI reviewer:

1. **Every rule finding cites its source.** A comment says ".editorconfig line 12 asks for 4-space
   indents" or "CONTRIBUTING.md line 41 asks for parameterised queries", and a deterministic validator
   drops any finding whose citation does not exist.
2. **Requirement traceability.** Acceptance criteria are pulled from the linked GitHub issue and from
   Markdown specs in the repository. Each criterion is marked met, partial or missing, with the code that
   meets it and the test that proves it. Changes no requirement asked for are listed as scope creep.

Goal: a project other people adopt, so installation friction and trust in the comments matter more than
feature count.

## Architecture

One deterministic core, with the reasoning step supplied by whichever host runs it
([ADR 0001](adr/0001-deterministic-core-swappable-reasoner.md)).

```
bylaw/
  context/     collects the diff, rule sources and requirements (no LLM)
  model.py     ReviewContext and Finding schemas (pydantic): the contract between parts
  prompts/     shared Markdown prompts: rules, security, requirements
  engine/      LLM call, used only in Action and CLI mode (Anthropic and OpenAI, structured output)
  validate.py  deterministic filter applied to every finding, whoever produced it
  publish/     GitHub review and summary comment
  cli.py       bylaw context | bylaw review | bylaw validate | bylaw post | bylaw prompts
```

Two modes share the core:

- **Action and CLI.** Pull request event, then `context`, then `engine` calls the LLM with the user's own
  key, then `validate`, then `publish`.
- **Claude Code and Codex.** The skill runs the PyPI release it was written for
  (`uvx bylaw@<version>`), so the CLI matches the skill's version. `bylaw context` and
  `bylaw prompt` write the context and the brief to files, the host model reviews against `bylaw
  schema`, and `bylaw validate` checks the result. `bylaw post --dry-run` shows the review; `bylaw
  post --pr` publishes it. No extra API key.

The same `context` command also works on a local branch with no pull request (`bylaw context --base
main`), so a developer can check their work against the rules and the spec before opening the PR.

Language: Python, distributed with `uvx` ([ADR 0002](adr/0002-python.md)).

### Finding

| Field | Meaning |
|---|---|
| `file`, `line_start`, `line_end` | Location, must fall on lines the diff touches |
| `category` | `security`, `bug`, `rule`, `requirement` |
| `severity` | `critical`, `high`, `medium`, `low`, `suggestion` |
| `message` | What is wrong, one or two sentences |
| `suggestion` | Optional replacement code, rendered as a GitHub suggestion block |
| `evidence` | Source of the finding: `CONTRIBUTING.md:41`, `issue#42/AC-3`, `docs/specs/auth.md/AC-1` |

### Validator

Drops a finding when:

- its lines are not part of the diff;
- its evidence names a file or line that does not exist in the collected context;
- it is a `rule` or `requirement` finding with no evidence;
- it repeats another finding: same lines, same category and same message.

The validator runs in every mode, so a host model is held to the same standard as the built-in engine.

## Rule sources

Read from the base branch, never from the pull request head
([ADR 0004](adr/0004-rules-from-base-branch.md)).

1. **`.editorconfig`.** Parsed and resolved per changed file. `indent_style`, `max_line_length`,
   `trim_trailing_whitespace`, `insert_final_newline` and `end_of_line` are checked on added lines
   without an LLM.
2. **Linter configuration.** `ruff.toml` and `pyproject.toml [tool.ruff]`, `eslint.config.*`,
   `.golangci.yml`, `.globalconfig` and analyzer settings, `.rubocop.yml`, `.prettierrc`. bylaw does not
   run linters; it passes the configuration for the languages in the diff to the model as line-numbered
   text the findings can cite. Ruff, ESLint JSON and YAML, golangci-lint and .NET analyzer settings are
   also parsed into the rule ids they enable, so a finding can cite `ruff:S608` and the validator drops
   an id the configuration governing the file turns off, or leaves off when bylaw read all of it.
   Configuration written as code stays text
   ([ADR 0013](adr/0013-nested-rules-and-linter-ids.md)).
3. **Prose rules.** `CONTRIBUTING.md`, `AGENTS.md`, `CLAUDE.md`, `.github/copilot-instructions.md`,
   `STYLEGUIDE.md`, line-numbered.

In a monorepo, a package's own `AGENTS.md`, `CLAUDE.md`, `CONTRIBUTING.md` and linter configuration apply
to the files under it, next to the root rules. For each changed file and each name, the nearest one above
it is read; directories without changed files are not. `.editorconfig` files cascade as the specification
says, so every one on the way up counts. The brief groups the rules by
directory and says the nearest wins, and the validator drops a citation of another package's rule
([ADR 0013](adr/0013-nested-rules-and-linter-ids.md)).
4. **Built-in language conventions.** Short packs (PEP 8, Effective Go, .NET naming) used only where the
   repository has no rule of its own. Evidence reads `bylaw:conventions/python#naming` and severity is
   capped at `suggestion`.

## Decisions

Accepted ADRs are a rule source of their own ([ADR 0016](adr/0016-adr-conformance.md)). bylaw lists the files
matching `adr_globs` (default `docs/adr/**`, `doc/adr/**`, `docs/decisions/**`) anywhere under each glob's
fixed directory on the base branch, leaves out READMEs, indexes and templates, and reads the newest 40 in
one GraphQL query. The status comes from a `Status:` line, table row or front matter key above the first
section, or from a `## Status` section, with links removed; it is read clause by clause and the last
clause that names a status decides, so "Accepted, superseded by 0012" is out and a history ending in
"accepted" is in. Accepted, approved, implemented, adopted and decided count; proposed and draft ADRs are
left out, and one note names the ADRs bylaw could not read. Headings in code fences do not count. The
brief's `decisions` block holds each one's title, effective status and decision section (`## Decision`, or
MADR's `## Decision Outcome`), numbered with the file's own lines, newest first: at most 2,000 characters
each and 12,000 in all, with a note for what was cut or left out. An ADR under a package
(`packages/api/docs/adr/`) binds only that package and is read only when the change touches it. A finding
that contradicts one is a `rule` finding citing `docs/adr/<file>.md:<line>`, and the validator keeps the
citation only for a line that was shown, on a file the decision binds. An ADR is never also a spec.

## Requirement sources

GitHub issues and Markdown files in the repository ([ADR 0003](adr/0003-requirement-sources.md)), and
since v0.4 work items in Jira, Azure Boards and Linear.

- **Issues:** closing keywords (`Closes`, `Fixes`, `Resolves`, with `#n` or `owner/repo#n`) in the PR
  body and commit messages, plus GraphQL `closingIssuesReferences`. Issue body only; comments are left
  out in v1. Only the pull request's own repository and repositories listed under `issue_repos` are read
  ([ADR 0007](adr/0007-issue-references-stay-in-the-repository.md)).
- **Spec files:** Markdown files linked from the PR body, plus changed files matching the spec glob
  (default `docs/specs/**`, `**/REQUIREMENTS.md`). ADRs are not specs: an accepted ADR is a decision the
  change is held to (see Decisions below).
- **Tracker work items:** Jira (`PROJ-123`), Azure Boards (`AB#123`) and Linear (`ENG-123`) keys in the
  PR title, body and commit messages, for trackers configured in `.bylaw.toml` with an allow list of
  projects or teams and a token in the environment. Rich text is turned into Markdown before criteria
  are extracted, and `quote_trackers = false` keeps their text out of the summary
  ([ADR 0014](adr/0014-tracker-requirements.md), setup in [trackers.md](trackers.md)).

Acceptance criteria are extracted deterministically first: task list items, items under headings named
"Acceptance criteria" or "Requirements", and Given/When/Then blocks. They are numbered `AC-1`, `AC-2` and
so on, from the issue body only. When a linked issue has no such structure, or has maintainer comments,
the reviewer derives up to five criteria in the same review call, labelled `IC-1` to `IC-5` and marked
`inferred` in the summary. Comments that trusted authors (owners, members, collaborators; a member who
wrote the pull request is left out) left on a linked issue are part of the requirement text ([ADR 0011](adr/0011-inferred-criteria-and-maintainer-comments.md)).

## Comments

- One review per run, with event `COMMENT`. bylaw never approves or requests changes. `fail-on: high`
  turns the check red instead, and blocking a merge is left to branch protection.
- Inline comments only at or above the severity threshold (default `medium`), at most 15 per run
  (configurable). Anything else goes into the summary. A problem repeated across many lines becomes one
  comment with "and N more places".
- **Summary comment.** One comment, found by a hidden `<!-- bylaw:summary -->` marker and edited in place
  on every run. It holds the requirement checklist (criterion, status, code evidence, test evidence),
  scope creep, counts per severity, the collapsed low severity findings and the rule sources used.
- **Fingerprint.** Each inline comment carries a hash of file, category, rule and normalised code
  snippet, without the line number, so shifting code does not change it.
- **Re-runs.** An existing fingerprint is not posted again. A fingerprint that disappeared means the issue
  was fixed and bylaw resolves its thread; if the problem comes back, bylaw reopens it. A maintainer
  mutes a finding by replying `bylaw: ignore`. Only comments from bots and from people with write access
  count ([ADR 0008](adr/0008-trusted-authors-carry-state.md)). State lives as hidden JSON in the summary
  comment ([ADR 0005](adr/0005-state-in-summary-comment.md)).

## Packaging

Prompts live in the Python package and the skills fetch them with `bylaw prompts`, so the three packages
cannot drift apart.

- **GitHub Action.** Composite `action.yml` at the repository root: `astral-sh/setup-uv`, then
  `uv run --project "$GITHUB_ACTION_PATH" --locked --no-dev bylaw review --post`, so a tag runs its own
  code with its own lock file ([ADR 0009](adr/0009-action-runs-from-its-own-source.md)). Inputs:
  `api-key`, `provider`, `model`, `effort`, `fail-on`, `github-token`. Without a key it runs the
  deterministic checks only. Listed on the GitHub Marketplace and versioned by tags (`v1`, `v1.2.0`).
- **Claude Code plugin.** The plugin lives in `plugin/`, apart from the source, so the plugin directories
  scan only what users install: `plugin/.claude-plugin/plugin.json`, `plugin/skills/bylaw-review/SKILL.md`
  and a `/bylaw-review` command. `.claude-plugin/marketplace.json` at the root points at it. Install: `/plugin marketplace add
  tunahanaliozturk/bylaw`, then `/plugin install bylaw@bylaw`.
- **Codex.** The same skill, through the portable `plugin/plugin.json` (Codex settings under `extensions."com.openai"`) and `.agents/plugins/marketplace.json`.
  Install: `codex plugin marketplace add tunahanaliozturk/bylaw`, then `/plugins`. The skill alone also
  works from `~/.agents/skills/`. The host model reviews in both hosts; bylaw supplies the context, the
  output schema (`bylaw schema`), the validation and the comments ([docs/hosts.md](hosts.md)).
- **PyPI** release through trusted publishing; no stored token.
- **GitHub App, self-hosted.** `bylaw-app` in the optional `app` extra, shipped as a container image. It
  verifies each webhook delivery, queues it by repository, pull request and head commit, and runs the
  same review flow as `bylaw review --pr N --post` with an installation token for one repository.
  Organisation defaults come from the `.github` repository, model keys per installation from a secret
  store ([ADR 0017](adr/0017-github-app.md), [docs/app/deploy.md](app/deploy.md)).

### Fork pull requests

On `pull_request`, fork PRs receive no secrets and a read-only token, so bylaw prints a notice and exits
cleanly. The documented recipe for fork PRs uses `pull_request_target`, which is safe for bylaw because it
never checks out or executes pull request code; an optional `labeled` trigger lets maintainers decide
which fork PRs spend API budget ([ADR 0006](adr/0006-pull-request-target-recipe.md)).

## Security

- Rule files and `.bylaw.toml` come from the base branch.
- Pull request, issue and spec text is untrusted. It enters the prompt as delimited data, and
  instructions inside it are not followed. A fixture with an injection attempt in the diff is part of the
  test suite.
- Action permissions: `contents: read`, `pull-requests: write`, `issues: read`. The app asks for the same,
  plus `metadata: read`, which every app has, and mints each token for one repository.
- bylaw never executes code from the pull request.

## Configuration

Works with no configuration. An optional `.bylaw.toml` sets the spec glob, severity threshold, disabled
categories, comment cap and token budget. Lockfiles, vendored code and files marked `linguist-generated`
are skipped; large pull requests are split into file groups.

## Testing and evaluation

- **Unit tests** on every PR: `.editorconfig` resolution, acceptance criteria extraction, closing keyword
  parsing, fingerprint stability under line shifts, each validator rule, summary state round trip, base
  branch config used when the PR edits `.bylaw.toml`, and the prompt injection fixture.
- **Contract tests** against recorded GitHub API responses (`respx`). No live GitHub or LLM calls in CI.
- **End to end** on a `bylaw-demo` repository with real pull requests.
- **Evaluation set** of 40 to 50 labelled pull requests with planted defects (SQL injection, hardcoded
  secret, path traversal, `.editorconfig` and `CONTRIBUTING` violations, missing acceptance criterion,
  scope creep) and clean pull requests. Reported per model and date: recall and precision per category,
  false positive rate on clean PRs, share of findings the validator dropped for invented citations, and
  cost and latency per PR. Run before a release, not on every CI run, because it costs money.
  The set, labels and matching rules: [docs/eval/README.md](eval/README.md).

## README images

Screenshots are real, never mocked: bylaw's actual comments on `bylaw-demo` pull requests captured with
Playwright (inline security finding, suggestion block, summary with the requirement checklist, local
terminal output), an architecture diagram, a logo and a social preview card. They live in
`docs/images/` and a script regenerates them.

## Out of scope for v1

- A hosted service. The GitHub App is self-hosted only ([ADR 0017](adr/0017-github-app.md)).
- A static analysis engine of our own: linter configuration is a rule source, linters are not re-run.
- Confluence and Notion as requirement sources. Jira, Azure Boards and Linear arrived in v0.4
  ([ADR 0014](adr/0014-tracker-requirements.md)).
- An MCP server; it can wrap the CLI later.
