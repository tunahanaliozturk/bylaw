# A reviewer that learns the repository

Roadmap: Q4 in [ROADMAP.md](../ROADMAP.md). Target: v1.0. Item ids: `LRN-n`.

When maintainers keep muting or resolving the same kind of finding without a change, bylaw should suggest a suppression or a rule clarification, in a pull request, never silently.

**Done when** a finding muted the configured number of times leads to a pull request that changes `.bylaw.toml` or the rules.

## Items

- [x] **LRN-1** (M) Per-fingerprint outcome in the summary state: fixed, muted, resolved without change. Done when: state tests.
- [ ] **LRN-2** (L) Outcome store across pull requests; ADR on where it lives. Done when: ADR and tests.
- [ ] **LRN-3** (M) Suggestion pull request when a threshold is reached. Done when: integration test.
- [x] **LRN-4** (S) `[learn]` setting, off by default. Done when: config test.
- [x] **LRN-5** (S) Summary lists active suppressions. Done when: render test.

## Notes

There is no server, so outcomes across pull requests need a store: a branch or Actions artifacts, decided in an ADR.
