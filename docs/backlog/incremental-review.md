# Incremental review

Roadmap: Q1 in [ROADMAP.md](../ROADMAP.md). Target: v0.2. Item ids: `INC-n`.

On a new push, review only what changed since the last run and carry the rest over, so long pull requests do not pay for the same review again and again.

**Done when** a second push to a reviewed pull request costs at most the size of the new commits, measured in the evaluation.

## Items

- [ ] **INC-1** (S) Save the reviewed head SHA and per-file fingerprints in the summary state. Done when: round-trip test on the state block.
- [ ] **INC-2** (L) Review only files and hunks changed since the saved SHA, and keep findings that still apply. Done when: unchanged files are not sent to the model; their open findings stay.
- [ ] **INC-3** (M) Fall back to a full review when the saved SHA is not an ancestor of the head. Done when: rebase and force-push tests.
- [ ] **INC-4** (M) Reassess only the criteria whose code or tests changed. Done when: other criteria keep their status and say since when.
- [ ] **INC-5** (S) Summary line naming the commits reviewed and the files carried over. Done when: render test.
- [ ] **INC-6** (S) `incremental = true | false` in `.bylaw.toml`, default true. Done when: config test.
- [ ] **INC-7** (M) Evaluation of the saving on a two-push replay of 10 cases. Done when: token numbers in the report.

## Notes

Needs care with rebases and force pushes; a full review is always the safe fallback.
