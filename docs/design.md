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
- **Claude Code and Codex.** The skill runs `uvx bylaw context`, the host model reviews with the prompts
  from `uvx bylaw prompts`, writes `findings.json`, and runs `bylaw validate`. Results print in the
  terminal, or go to the pull request with `--post`. No extra API key.

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
- it duplicates another finding on the same lines.

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
   text the findings can cite.
3. **Prose rules.** `CONTRIBUTING.md`, `AGENTS.md`, `CLAUDE.md`, `.github/copilot-instructions.md`,
   `STYLEGUIDE.md`, line-numbered.
4. **Built-in language conventions.** Short packs (PEP 8, Effective Go, .NET naming) used only where the
   repository has no rule of its own. Evidence reads `bylaw:conventions/python#naming` and severity is
   capped at `suggestion`.

## Requirement sources

GitHub issues and Markdown files in the repository ([ADR 0003](adr/0003-requirement-sources.md)).

- **Issues:** closing keywords (`Closes`, `Fixes`, `Resolves`, with `#n` or `owner/repo#n`) in the PR
  body and commit messages, plus GraphQL `closingIssuesReferences`. Issue body only; comments are left
  out in v1.
- **Spec files:** Markdown files linked from the PR body, plus changed files matching the spec glob
  (default `docs/specs/**`, `docs/adr/**`, `**/REQUIREMENTS.md`).

Acceptance criteria are extracted deterministically first: task list items, items under headings named
"Acceptance criteria" or "Requirements", and Given/When/Then blocks. They are numbered `AC-1`, `AC-2` and
so on. When a document has no such structure, the model extracts criteria from the prose and they are
marked `inferred` and shown with lower confidence.

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
  was fixed and its thread is resolved. A thread resolved by a person, or answered with `bylaw: ignore`,
  is muted. This state lives as hidden JSON in the summary comment
  ([ADR 0005](adr/0005-state-in-summary-comment.md)).

## Packaging

Prompts live in the Python package and the skills fetch them with `bylaw prompts`, so the three packages
cannot drift apart.

- **GitHub Action.** Composite `action.yml` at the repository root: `astral-sh/setup-uv`, then `uvx
  bylaw@<pinned version> review`. Inputs: `provider`, `model`, `api-key`, `fail-on`, `max-comments`.
  Listed on the GitHub Marketplace and versioned by tags (`v1`, `v1.2.0`).
- **Claude Code plugin.** `.claude-plugin/plugin.json` and `marketplace.json` in the same repository, with
  `skills/bylaw-review/SKILL.md` and a `/bylaw-review [pr]` command.
- **Codex.** The same `SKILL.md`, plus an `AGENTS.md` snippet. The exact install path is to be taken from
  the Codex documentation at implementation time.
- **PyPI** release through trusted publishing; no stored token.

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
- Action permissions: `contents: read`, `pull-requests: write`, `issues: read`.
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

## README images

Screenshots are real, never mocked: bylaw's actual comments on `bylaw-demo` pull requests captured with
Playwright (inline security finding, suggestion block, summary with the requirement checklist, local
terminal output), an architecture diagram, a logo and a social preview card. They live in
`docs/images/` and a script regenerates them.

## Out of scope for v1

- A hosted service or GitHub App.
- A static analysis engine of our own: linter configuration is a rule source, linters are not re-run.
- Jira, Azure DevOps, Confluence and Notion as requirement sources.
- Issue comments as requirement text.
- An MCP server; it can wrap the CLI later.
