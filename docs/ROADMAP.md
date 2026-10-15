# Roadmap

Each milestone ends with something a user can run. Design: [design.md](design.md). Decisions:
[adr/](adr/).

## M0: decisions and design (done, 2026-10-15)

- Design document and ADRs 0001 to 0006.

## M1: context without a model (done, 2026-10-15)

- Python package skeleton, CI gates (lint, strict typing, tests, licence audit).
- `bylaw context` for a GitHub pull request and for a local branch (`--base main`).
- `.editorconfig` resolution and the deterministic checks on added lines.
- Rule source collection from the base branch.
- Requirement collection from closing keywords and spec files, acceptance criteria extraction.
- Exit: `bylaw context --pr N` prints a `ReviewContext` JSON for a real pull request, and the
  `.editorconfig` findings are correct without any LLM call.

## M2: findings, validator, comments

- `Finding` schema, `bylaw validate`, `bylaw post`.
- Summary comment with hidden marker and state, inline comments with fingerprints, re-run behaviour.
- Exit: a hand-written `findings.json` posts correctly, and a second run on a new commit resolves fixed
  threads and posts nothing twice.

## M3: built-in engine and the GitHub Action

- `engine` for Anthropic and OpenAI with structured output, shared prompts, `bylaw review`.
- Composite `action.yml`, `pull_request` and `pull_request_target` recipes, `fail-on`.
- `bylaw-demo` repository with seeded pull requests.
- Exit: the Action reviews a demo pull request end to end with the user's own key.

## M4: Claude Code plugin and Codex skill

- `SKILL.md`, `/bylaw-review` command, plugin and marketplace manifests.
- Codex install path verified against the Codex documentation.
- Exit: the same demo pull request reviewed from Claude Code and from Codex with no extra key.

## M5: evaluation

- Labelled set of 40 to 50 pull requests, eval runner, results table per model and date.
- Exit: README numbers come from a committed eval run.

## M6: v0.1.0 release

- README with real screenshots, architecture diagram, logo and social preview.
- PyPI trusted publishing, Action tags, Marketplace listing.
- Exit: `uvx bylaw` and `uses: tunahanaliozturk/bylaw@v0` work from a clean machine.

## Later

Ideas, not commitments:

- Jira and Azure DevOps work items as requirement sources.
- Issue comments as requirement text.
- Incremental review of only the new commits, to cut cost on long pull requests.
- An MCP server wrapping the CLI.
- A GitHub App for organisations that do not want to manage workflow files.
