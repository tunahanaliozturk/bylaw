# Fix pull requests

Roadmap: End of 2027 in [ROADMAP.md](../ROADMAP.md). Target: v1.1. Item ids: `FIX-n`.

Where a maintainer turns it on, bylaw opens a pull request with fixes into the reviewed branch. It never pushes to someone else's branch.

**Done when** with `[fix] mode = "pull-request"`, a reviewed pull request gets one fix pull request that links back, runs CI and is merged by a person.

## Items

- [ ] **FIX-1** (M) ADR: fix pull request design, token scope, triggers. Done when: ADR accepted.
- [ ] **FIX-2** (S) `[fix]` settings (mode, scope, max_lines) read from the base branch. Done when: config tests.
- [ ] **FIX-3** (M) Deterministic fixers for `.editorconfig`: indentation, trailing whitespace, final newline. Done when: fixer tests.
- [ ] **FIX-4** (L) Apply validated suggestions as commits on `bylaw/fix/<number>`, one commit per fix. Done when: integration tests.
- [ ] **FIX-5** (M) Open, update and close one fix pull request; the body names the reviewed pull request and its issues and work items (`Refs`). Done when: fake server tests.
- [ ] **FIX-6** (S) Never touch workflows, rule files, `.bylaw.toml`, lock files or files outside the pull request. Done when: tests.
- [ ] **FIX-7** (M) `/bylaw fix` comment trigger for trusted authors. Done when: tests.
- [ ] **FIX-8** (S) A fix pull request closed unmerged mutes those fixes on the next run. Done when: tests.
- [ ] **FIX-9** (M) Evaluation: share of suggestions that apply cleanly and keep tests green. Done when: report.

## Notes

Needs `contents: write`; never with `pull_request_target` on a fork.
