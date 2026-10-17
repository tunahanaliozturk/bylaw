# Incremental review

Roadmap: Q1 in [ROADMAP.md](../ROADMAP.md). Target: v0.2. Item ids: `INC-n`.

On a new push, review only what changed since the last run and carry the rest over, so long pull requests do not pay for the same review again and again.

**Done when** a second push to a reviewed pull request costs at most the size of the new commits, measured in the evaluation.

## Items

- [x] **INC-1** (S) Save the reviewed head SHA and per-file fingerprints in the summary state. Done when: round-trip test on the state block.
- [x] **INC-2** (L) Review only files and hunks changed since the saved SHA, and keep findings that still apply. Done when: unchanged files are not sent to the model; their open findings stay.
- [x] **INC-3** (M) Fall back to a full review when the saved SHA is not an ancestor of the head. Done when: rebase and force-push tests. Done differently (ADR 0012): files are compared by the hash of their change, not by commit ancestry, so a rebase or force push keeps what did not change and reviews the rest; covered by the changed-file and changed-inputs tests.
- [x] **INC-4** (M) Reassess only the criteria whose code or tests changed. Done when: other criteria keep their status and say since when.
- [x] **INC-5** (S) Summary line naming the commits reviewed and the files carried over. Done when: render test.
- [x] **INC-6** (S) `incremental = true | false` in `.bylaw.toml`, default true. Done when: config test.
- [x] **INC-7** (M) Evaluation of the saving on a two-push replay of 10 cases. Done when: token numbers in the report. Done on the 17 cases that change two or more files, with estimated tokens and no model call: 9% less input on average, up to 18% (eval/results/2026-10-18-incremental-saving.md).

## Notes

The fixed part of every run (system prompt, rules, requirements) is sent again on each push, so a second push costs that plus the changed files, not only the new commits. The evaluation cases are small, which makes the fixed part a large share; the saving grows with the size of the pull request.


Needs care with rebases and force pushes; a full review is always the safe fallback.
