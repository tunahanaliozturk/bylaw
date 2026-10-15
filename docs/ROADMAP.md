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

## M2: findings, validator, comments (done, 2026-10-15)

- `Finding` schema, `bylaw validate`, `bylaw post`.
- Summary comment with hidden marker and state, inline comments with fingerprints, re-run behaviour.
- Exit: a hand-written `findings.json` posts correctly, and a second run on a new commit resolves fixed
  threads and posts nothing twice.

## M3: built-in engine and the GitHub Action (done, 2026-10-15; live model run deferred)

- `engine` for Anthropic and OpenAI with structured output, shared prompts, `bylaw review`.
- Composite `action.yml`, `pull_request` and `pull_request_target` recipes, `fail-on`.
- `bylaw-demo` repository with seeded pull requests.
- Exit: the Action reviews a demo pull request end to end without a key; the live model run on the
  demo repository happens at the end of the project.

## M4: Claude Code plugin and Codex skill (done, 2026-10-15)

- `SKILL.md`, `/bylaw-review` command, plugin and marketplace manifests.
- Codex install path verified against the Codex documentation.
- Exit: the same demo pull request reviewed from Claude Code and from Codex with no extra key.

## M5: evaluation (set and tooling done, 2026-10-15)

- Labelled set of 50 pull requests in four languages, `bylaw eval prepare`, `run` and `score`, results per
  model and date ([docs/eval/README.md](eval/README.md), [ADR 0010](adr/0010-evaluation-on-planted-cases.md)).
- Exit: README numbers come from a committed eval run. Waiting for the first paid model run.

## M6: v0.1.0 release

- README with real screenshots, architecture diagram, logo and social preview.
- PyPI trusted publishing, Action tags, Marketplace listing.
- On going public: a ruleset on `main` (pull request required, `checks` and `tests` green, linear
  history, no force push or deletion), secret scanning with push protection, private vulnerability
  reporting and CodeQL. GitHub offers these on private repositories only with a paid plan.
- Exit: `uvx bylaw` and `uses: tunahanaliozturk/bylaw@v0` work from a clean machine.

## M7: requirements from prose and maintainer comments (done, 2026-10-15)

- Reviewers derive up to five acceptance criteria for an issue or spec written as prose; the summary marks
  them inferred. Trusted authors' comments on a linked issue are part of the requirement
  ([ADR 0011](adr/0011-inferred-criteria-and-maintainer-comments.md)).
- Exit: `bylaw-demo` pull request 5 closes a prose issue with a maintainer comment; the summary lists four
  inferred criteria, including the one from the comment.

## Later

Ideas, not commitments:

- Jira and Azure DevOps work items as requirement sources.
- Incremental review of only the new commits, to cut cost on long pull requests.
- An MCP server wrapping the CLI.
- A GitHub App for organisations that do not want to manage workflow files.

Known gaps from reviews, small and not yet scheduled:

- Renamed-only, mode-only and empty files get the "binary or too large" note.
- An invalid glob such as `[z-a]` in a base `.editorconfig` ends the run with a traceback.
- The note about skipped lock, vendored and generated files gives a count, not the paths.
- Nothing says so when GitHub's 3000-file listing cap cuts a pull request short.
- If posting fails partway, the summary's saved state can disagree with the comments already posted.
- Two findings on identical lines in one file share a fingerprint, so one can hide the other.
- `bylaw post --dry-run` previews with the default config, not the base branch's `.bylaw.toml`.
- Thread replies past the first 50 are not read, so a late mute or resolve can be missed.
- The Anthropic call caps output at 20,000 tokens and does not stream.
- The prompt budget counts characters, not tokens.
- With the `pull_request_target` recipe, adding or removing a label re-runs the review.
- `/bylaw-review` reads `post` as a base branch name, does not accept `#12` or a PR URL, takes `owner/name`
  from `origin` (wrong on a fork) and defaults to `main` even on `master` repositories.
- `--base` reviews committed changes only, and the skill does not tell the user so.
- In `--pr` mode the skill may open local files that differ from the pull request's head.
- The Codex manifest's default prompt names pull request 12, and a public Codex listing needs fields it
  does not have yet (`websiteURL`, `privacyPolicyURL`, `logo`, `composerIcon`).
- Evaluation: a failed paid attempt (refusal, truncated output) is billed but its tokens are not recorded.
- `bylaw eval run` exits 0 when some cases failed, does not mention `BYLAW_API_KEY` when no key is set,
  and starts all 50 cases without showing the count first.
- An evaluation case directory without `case.toml` is skipped silently, and nothing checks that a case's
  kind matches its labels.
- Rule findings in the evaluation are matched by place and category, not by the rule line they cite.
- `cs-async-void` accepts only the declaration, not the fire-and-forget call, as the place of the defect.
- Throwaway evaluation repositories run the user's global git hooks; a failing hook ends the run with a
  traceback.
- A linked issue whose comments cannot be read (moved or hidden between two calls) ends the review instead
  of going on without the comments.
- Summary cells show 80 characters, so an inferred criterion of up to 300 is cut.
- Maintainer comments sit under an in-band heading that an issue body could imitate.
- Hidden (minimised) issue comments still count; the REST API does not report them.
