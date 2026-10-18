# 0015: A second evaluation set of frozen real pull requests

Status: Accepted, 2026-10-18

## Context

ADR 0010 chose planted cases because their labels are certain, and named the price: realism. Real pull requests are larger, mix concerns, and carry project rules and issues bylaw has never seen. The roadmap asks for 20 to 30 of them, labelled by two people and reported apart from the planted set.

Three things make that harder than it sounds. A run must never read live data, or the score changes when a project rewrites a file or edits an issue. Copying third-party code needs a licence that allows it. And a real pull request has no "planted defect", so a label has to come from somewhere a reader can check.

## Decision

- **Selection** follows [docs/eval/real-set.md](../eval/real-set.md): a merged pull request in an MIT, Apache-2.0 or BSD project, with a linked issue, where a reviewer's inline comment named a problem and a later commit fixed it.
- **A case is the pull request at the reviewed commit**, diffed from its merge base, because that is what the reviewer saw and where the problem still is. The review comment is kept in the snapshot as evidence for labellers; bylaw never sees it.
- **`bylaw eval snapshot`** reads the pull request through the GitHub API once and freezes it. It runs bylaw's own context collection against a recording source, so the snapshot holds exactly the files bylaw reads (the touched files at both ends, `.editorconfig`, linter configs, `CONTRIBUTING.md` and the like, linked specs) and the issues it reads, and nothing else. A tree read answers the "does this rule file exist" questions in one call. The project's licence text, and an Apache `NOTICE`, are copied next to it. Before the snapshot is kept, the tool builds it as a case and checks the diff matches GitHub's line for line.
- **A run replays the snapshot** through `build_case_context`, like a planted case: a throwaway git repository with the base files, then the head files, read by `LocalGitSource`. A thin subclass answers the title, body, commit messages and issues from `snapshot.json`. Nothing in that path opens a connection, and a test fails if it does.
- **The real set has its own root, `eval/real/`.** `bylaw eval run --set eval/real` and `bylaw eval score --set eval/real` work on it with no new flags.
- **The report keeps the sets apart** by the case, not by the directory: planted cases, real cases two people labelled, and real cases with fewer than two labellers each get their own section and their own score. A model's first pass counts as nobody, so those cases are reported as provisional and are never quoted.
- **Labels live in `case.toml` next to the snapshot**, in the planted format plus `labellers` and `disagreements`. The tool owns `snapshot.json`; people own `case.toml`, so freezing a pull request again never overwrites a label.

## Consequences

- Runs are reproducible and offline. The cost is a committed copy of each project's touched files; the set is kept small by the size rule and by copying only what bylaw reads.
- The same matching rules apply to both sets, so a reader can compare them. The numbers mean different things, though: on a real case a "false alarm" can be a problem nobody reported, so real precision is a lower bound and the report says so.
- Paid runs on the planted set cost what they did, and committed planted reports are unchanged, because the real set is not in the default root.
- Issue comments are frozen as bylaw read them (trusted authors only, ADR 0011), and the pull request body is today's, not the body at the reviewed commit. Body edits after a review are rare and the issue is the requirement that matters.
- A force-pushed pull request whose reviewed commit is gone cannot be snapshotted. The selection rules exclude it.
- Until two people label each case, the real set checks the tooling and the labels' reachability, not the reviewer.

## Alternatives

- **One root holding both sets, scored together by default.** Lost because every paid planted run would also review the real cases, and every committed planted report would grow a section of "no run" errors. The report still partitions by case, so a root that holds both works if someone wants it.
- **Fetching the pull request at run time.** Lost because a run would depend on GitHub being up and on history nobody controls, and a rate limit would end it half way.
- **Snapshotting the merged head.** Lost because the problem the reviewer found is already fixed there; every real case would look clean.
- **Copying the whole repository at the base commit.** Lost on size: one mid-sized project is tens of megabytes, and bylaw reads a dozen files of it.
- **A hand-written list of rule files to copy.** Lost because it would drift from what `build_context` reads; recording the real reads keeps the snapshot right when the rule collection changes.
