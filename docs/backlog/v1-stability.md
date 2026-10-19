# v1.0 stability

Roadmap: Q4 in [ROADMAP.md](../ROADMAP.md). Target: v1.0. Item ids: `V1-n`.

Promise users that configuration and results will not break under them.

**Done when** versioned configuration and result schema, a deprecation policy, and the evaluation published for every supported model.

## Items

- [x] **V1-1** (M) `version = 1` in `.bylaw.toml` and in the result schema; unknown versions fail clearly. Done when: tests.
- [x] **V1-2** (S) Deprecation policy: warnings one minor release before removal. Done when: docs page.
- [x] **V1-3** (M) Compatibility tests on results recorded with 0.x. Done when: tests.
- [ ] **V1-4** (M) Fresh whole-tool security review; `SECURITY.md` updated. Done when: review report.
