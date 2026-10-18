# 0015: A second evaluation set of frozen real pull requests

Status: Accepted, 2026-10-18

## Context

ADR 0010 chose planted cases because their labels are certain, and named the price: realism. Real pull requests are larger, mix concerns, and carry project rules and issues bylaw has never seen. The roadmap asks for 20 to 30 of them, labelled by two people and reported apart from the planted set.

Three things make that harder than it sounds. A run must never read live data, or the score changes when a project rewrites a file or edits an issue. Copying third-party code needs a licence that allows it. And a real pull request has no "planted defect", so a label has to come from somewhere a reader can check.

## Decision

- **Selection** follows [docs/eval/real-set.md](../eval/real-set.md): a merged pull request in an MIT, Apache-2.0 or BSD project, with a linked issue, where a reviewer's inline comment named a problem and a later commit fixed it.
- **A case is the pull request at the reviewed commit**, diffed from its merge base, because that is what the reviewer saw and where the problem still is. The review comment is kept in the snapshot as evidence for labellers; bylaw never sees it.
- **`bylaw eval snapshot`** reads the pull request through the GitHub API once and freezes it. It runs bylaw's own context collection against a recording source, so the snapshot holds exactly the files bylaw reads (the touched files at both ends, `.editorconfig`, linter configs, `CONTRIBUTING.md` and the like, linked specs) and the issues it reads, and nothing else. A tree read answers the "does this rule file exist" questions in one call. The licence is the one GitHub detects **at the merge base**, the commit the files are copied from, not today's default branch, because a project can relicense or reword its notice later. Its text and every root `NOTICE*` file at that commit are copied next to the snapshot.
- **The tool refuses what it cannot copy faithfully or lawfully:**
  - a touched file whose header names another licence (an `SPDX-License-Identifier` that differs from the project's, or the GNU or Mozilla public licences);
  - a change without a text diff, such as a binary file;
  - bytes that are not UTF-8;
  - a touched file over 60 KB;
  - a path a git tree allows but Windows reads as a way out (backslashes, device names, trailing dots);
  - a case id that is not a plain name.

  It writes into a staging directory and swaps it in only after the replay check passes: the case is built and its changed paths and added lines, text included, must match GitHub's. A failed freeze leaves the previous snapshot as it was.
- **A run replays the snapshot** through `build_case_context`, like a planted case: a throwaway git repository with the base files, then the head files, read by `LocalGitSource`. A thin subclass answers the title, body, commit messages and issues from `snapshot.json`. The context is built with an empty environment, so a frozen `.bylaw.toml` that configures Jira, Linear or Azure Boards can never reach a tracker with the developer's tokens. Nothing in that path opens a connection: `tests/integration/test_eval_real_set.py` builds every committed case with sockets patched to fail.
- **The real set has its own root, `eval/real/`.** `bylaw eval run --set eval/real` and `bylaw eval score --set eval/real` work on it with no new flags.
- **The report keeps the sets apart** by the case, not by the directory: planted cases, real cases two people labelled, and real cases with fewer than two labellers each get their own section and their own score. A model's first pass counts as nobody, so those cases are reported as provisional and are never quoted.
- **Labels live in `case.toml` next to the snapshot**, in the planted format plus `labellers` and `disagreements`. The tool owns `snapshot.json`; people own `case.toml`, so freezing a pull request again never overwrites a label.

## Consequences

- Runs are reproducible and offline. The cost is a committed copy of each project's touched files; the set is kept small by the size rule and by copying only what bylaw reads.
- The same matching rules apply to both sets, so a reader can compare them. The numbers mean different things, though: on a real case a "false alarm" can be a problem nobody reported, so real precision is a lower bound and the report says so.
- Paid runs on the planted set cost what they did, and committed planted reports are unchanged, because the real set is not in the default root.
- The issue text and its comments are as of snapshot time, frozen as bylaw read them (trusted authors only, ADR 0011), not as they stood at the reviewed commit. The pull request body is also today's. Edits after a review are rare and the issue is the requirement that matters.
- **Personal data.** A snapshot keeps what bylaw reads plus the review comment the case is built around: the pull request's title, body and commit messages, the issue's text and trusted comments, and the comment's body and URL. Logins and names appear where people wrote them into that text, because the text is the input being measured. Commit trailers (`Signed-off-by:`, `Co-authored-by:` and the like) and email addresses are removed, because bylaw never reads them and they are the most personal part. Anyone who wants their words out of a case can open an issue, and the case is re-frozen or dropped.
- A force-pushed pull request whose reviewed commit is gone cannot be snapshotted. The selection rules exclude it.
- Until two people label each case, the real set checks the tooling and the labels' reachability, not the reviewer.

## Alternatives

- **One root holding both sets, scored together by default.** Lost because every paid planted run would also review the real cases, and every committed planted report would grow a section of "no run" errors. The report still partitions by case, so a root that holds both works if someone wants it.
- **Fetching the pull request at run time.** Lost because a run would depend on GitHub being up and on history nobody controls, and a rate limit would end it half way.
- **Snapshotting the merged head.** Lost because the problem the reviewer found is already fixed there; every real case would look clean.
- **Copying the whole repository at the base commit.** Lost on size: one mid-sized project is tens of megabytes, and bylaw reads a dozen files of it.
- **A hand-written list of rule files to copy.** Lost because it would drift from what `build_context` reads; recording the real reads keeps the snapshot right when the rule collection changes.
