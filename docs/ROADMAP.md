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
- Exit: README numbers come from a committed eval run: done 2026-10-16 with `claude-opus-5-5` (eval/results/2026-10-16-opus-5-5).

## M6: v0.1.0 release (released 2026-10-16)

- README with real screenshots, architecture diagram, logo and social preview.
- PyPI trusted publishing, Action tags, Marketplace listing.
- Done on going public (2026-10-16): a ruleset on `main` (pull request required, `checks` and `tests`
  green, linear history, no force push or deletion), secret scanning with push protection, private
  vulnerability reporting, and a CodeQL workflow for Python and Actions that leaves `eval/` out.
- Exit: `uvx bylaw` and `uses: tunahanaliozturk/bylaw@v0` work from a clean machine.

## M7: requirements from prose and maintainer comments (done, 2026-10-15)

- Reviewers derive up to five acceptance criteria for an issue or spec written as prose; the summary marks
  them inferred. Trusted authors' comments on a linked issue are part of the requirement
  ([ADR 0011](adr/0011-inferred-criteria-and-maintainer-comments.md)).
- Exit: `bylaw-demo` pull request 5 closes a prose issue with a maintainer comment; the summary lists four
  inferred criteria, including the one from the comment.

## The next fourteen months (November 2026 to December 2027)

The direction: be the reviewer that checks a change against what the team already wrote down, rules and
requirements, with numbers to show it. Each quarter ends with a release and a fresh evaluation run, so
every claim in the README stays measured. Dates are targets, not promises; the order matters more.

### Q1, November 2026 to January 2027: launch and earn trust (v0.1, v0.2; v0.2 released 2026-10-18)

- Finish M6: the first paid evaluation run, README numbers and real screenshots, PyPI with trusted
  publishing, `v0` Action tag, GitHub Marketplace listing, Claude Code and Codex plugin listings.
- Announce once, with the evaluation as the story: Show HN, the Claude Code and Codex communities.
- Incremental review: on a new push, review only the commits since the last run and carry the rest of
  the summary over. Cuts cost on long pull requests, which is the first complaint any paid reviewer gets.
- Close the [hardening](backlog/hardening.md) items that users are most likely to meet.
- Measure: installs, stars, cost per pull request, false alarms on the clean evaluation cases.

### Q2, February to April 2027: deeper rules and requirements (v0.3, v0.4; both released 2026-10-18)

- Linter configuration as structured rules: read the enabled rule ids from Ruff, ESLint, golangci-lint and
  .NET analyzers configs, so findings cite the rule id, not only the file line.
- Nested instructions in monorepos: the closest `AGENTS.md`, `CONTRIBUTING.md` or `.editorconfig` applies
  to each changed file.
- ADR conformance: flag a change that contradicts an accepted ADR in the repository, cited by file and
  line.
- Requirement sources beyond GitHub issues: Jira, Linear and Azure DevOps work items, read only for
  references the pull request makes, each behind an explicit opt-in like `issue_repos` (ADR 0007).
- Evaluation set v2: add 20 to 30 real pull requests from permissive open-source projects with labels
  agreed by two people, next to the planted set (the alternative ADR 0010 deferred).

### Q3, May to July 2027: more places to run (v0.5, v0.6; v0.5 released 2026-10-19 with the GitHub App and the model providers)

- A GitHub App, for organisations that do not want a workflow file per repository: one install, central
  configuration, the same deterministic core.
- GitLab merge requests, then Bitbucket if users ask: the context and publish layers are the only parts
  that change (ADR 0001).
- More model providers: Amazon Bedrock, Google Vertex AI, Azure, and local models through an
  OpenAI-compatible endpoint, for teams that cannot send code to a public API.
- An MCP server wrapping the CLI, so any agent can ask for a bylaw review.
- Compliance profiles, ISO/IEC 27001 first: a team switches a profile on in `.bylaw.toml`, and bylaw
  reviews with the standard's development controls in mind, tags findings with the Annex A control they
  touch, and leaves change-management evidence per pull request for audits. It helps with evidence; it
  does not make anyone compliant. SOC 2, PCI DSS, OWASP ASVS, GDPR and KVKK can follow in the same format.

### Q4, August to October 2027: a reviewer that learns the repository (v1.0)

- Learn from maintainers: when a finding is muted or resolved without a change several times, suggest a
  `.bylaw.toml` suppression or a rule clarification in a pull request, never silently.
- A per-repository report: findings by category, how many were fixed, muted or ignored, and criteria met
  over time, as a static page the Action can publish.
- v1.0: a stable configuration and result schema with versioning, a deprecation policy, and the
  evaluation published for every supported model.

### End of 2027, November and December: fixes, when you turn them on (v1.1)

Everything above comments; from here bylaw may also change code, but only where a maintainer switched it
on. One setting in `.bylaw.toml`, read from the base branch like every other setting (ADR 0004), so a
pull request cannot turn it on for itself:

```toml
[fix]
mode = "off"            # off (default) | suggest | pull-request
scope = ["editorconfig"] # what may be fixed: editorconfig, rule, bug, security
max_lines = 40          # a fix larger than this stays a comment
```

- `suggest`: what bylaw does today, a GitHub suggestion block a person applies with one click.
- `pull-request`: bylaw commits the fixes on a branch of its own and opens a pull request into the
  reviewed pull request's branch, titled after it and linked from the summary. The author or a
  maintainer reviews and merges it like any other change; bylaw never pushes to someone else's branch.
  Only for branches in the same repository, never forks.
- A maintainer can also ask for one fix pull request by commenting `/bylaw fix` on the pull request.

What stays true:

- Off by default. Deterministic fixes come first (tabs, trailing whitespace, final newlines), model fixes
  only for the categories listed in `scope`.
- A fix goes into the fix pull request only when it is the exact `suggestion` a validated finding carried
  and applies cleanly. Anything else stays a comment. The repository's own CI runs on the fix pull
  request as on any other, so a fix that breaks a test shows red before anyone merges it.
- bylaw never edits workflow files, rule files, `.bylaw.toml`, lock files or anything the pull request
  did not touch, and never force-pushes.
- One fix pull request per reviewed pull request at a time: a new run updates it rather than opening
  another, and closes it when the fixes are no longer needed.
- Every fix is its own commit, labelled as bylaw's; closing the fix pull request unmerged mutes those
  fixes on the next run.
- The fix pull request links back: it names the reviewed pull request and the issues and work items that
  pull request implements (`Refs #12`, the Jira or Azure DevOps key), so the trail from requirement to
  fix stays in one place. It never uses a closing keyword; closing the issue stays with the original pull
  request.
- Opening branches and pull requests needs a token with `contents: write`, so this mode works only with
  the `pull_request` trigger or a maintainer's `/bylaw fix` comment, never with `pull_request_target` on a
  fork. This gets its own ADR before any code.

The learning work in Q4 feeds this: fixes that maintainers keep closing unmerged turn back into comments
for that repository, and the summary says why.

### Beyond 2027: the tracker as both input and output

Q2 makes Jira, Linear and Azure DevOps sources bylaw reads requirements from. The next step uses the same
connections in both directions, again only where a maintainer turns it on:

- **Follow-up tasks.** Findings that should not block the pull request (a missing test for an old path, a
  rule broken in code the change only touched, a criterion left `partial` on purpose) can become a GitHub
  issue, a Jira issue or an Azure DevOps task when the pull request merges, linked to the pull request and
  the original requirement. Each task carries the finding's fingerprint, so a later run updates it instead
  of opening a duplicate, and closes it when the fix lands.
- **Fix tasks.** A work item that a maintainer labels for bylaw (for example `bylaw:fix`) and that names a
  finding or a file becomes a fix pull request, with the same limits as the fix setting above: a pull
  request, never a push; the repository's CI runs on it; a person merges it.
- **Status back to the tracker.** The work item a pull request implements gets a short note with the
  criteria bylaw found met, partly met or missing, so a project manager sees it without opening GitHub.

Writing to a tracker needs a token for that tracker and sends repository text to it, so each of these is
a separate opt-in in `.bylaw.toml` on the base branch, with its own ADR covering what is sent and who can
trigger it.

### What would change this plan

- If the paid evaluation shows high false alarm rates, precision work moves ahead of everything in Q2.
- If most users come through Claude Code or Codex rather than the Action, the plugin path gets the
  incremental review and the reports first.
- If fix pull requests are mostly closed unmerged in early use, they stay limited to deterministic
  fixes until the model fixes measure better in the evaluation.
- If organisations ask for it, the GitHub App moves to Q2. A hosted, paid service stays out of scope until
  the open-source tool has steady users.

## Backlog

Every step above is broken into items in [backlog/](backlog/README.md), one file per feature. Known gaps from
the milestone reviews are in [backlog/hardening.md](backlog/hardening.md).
