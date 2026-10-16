# Tracker tasks in both directions

Roadmap: Beyond 2027 in [ROADMAP.md](../ROADMAP.md). Target: v1.2+. Item ids: `TSK-n`.

Use the tracker connections from TRK to write as well as read: follow-up tasks, fix tasks and status notes.

**Done when** each direction works for GitHub issues first, then Jira and Azure DevOps, each behind its own opt-in.

## Items

- [ ] **TSK-1** (M) ADR: what is sent to trackers and who can trigger it. Done when: ADR accepted.
- [ ] **TSK-2** (L) Follow-up tasks on merge for findings that should not block, with fingerprint dedupe and closing when fixed. Done when: fake server tests.
- [ ] **TSK-3** (L) Fix tasks: a work item labelled `bylaw:fix` becomes a fix pull request (needs FIX). Done when: integration tests.
- [ ] **TSK-4** (M) Status note on the implemented work item: criteria met, partly met or missing. Done when: fake server tests.
- [ ] **TSK-5** (S) Separate opt-ins in `.bylaw.toml`. Done when: config tests.

## Notes

Writing sends repository text to the tracker; each direction gets its own ADR.
