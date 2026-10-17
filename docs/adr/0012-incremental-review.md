# 0012: Incremental review by file content, remembered in a bot's summary

Status: Accepted, 2026-10-18. Builds on 0005 and 0008.

## Context

Every push to a pull request runs bylaw again, and until now every run sent the whole change to the model.
On a long pull request that is reviewed after each small fix, most of what the model reads is the same as
last time, and the team pays for it again. A cheaper second run needs to know what the last run saw and
said, and the only storage bylaw has is the summary comment (ADR 0005).

## Decision

The summary state gains a review memory: for each file the model read, a hash of its change against the
base; the model's findings, criteria and scope notes; and the tokens spent. On the next run a file whose
change hashes the same is carried over: the model does not see it, its earlier findings stand, and the
model is told which files it is not shown. Everything else goes to the model.

- **Content, not commits.** A file counts as unchanged when its change is byte for byte what it was, not
  when the saved head is an ancestor of the new one. A rebase or force push that keeps a file's change
  keeps its review; one that changes it gets it reviewed again. There is no ancestry case to get wrong.
- **What forces a full review:** different rules, different requirements, or another bylaw version
  (hashed together), no memory, or `incremental = false` in `.bylaw.toml`.
- **Criteria.** A criterion that was met stays met, with "unchanged since <commit>", while every file it
  was met in is unchanged. Partial and missing criteria are always asked again: new code may meet them.
- **When the model does not run** (no key, an error, or the pull request reached `[budget] pr_tokens`),
  the earlier findings stand instead of being resolved as fixed. Validation still drops any that no
  longer fit the code.
- **Trust.** The memory decides what the model skips, so it is read only from a summary written by a bot
  account. ADR 0008 also accepts a summary written by an `OWNER`, `MEMBER` or `COLLABORATOR`, and an
  organisation member with read access could otherwise post a fake summary claiming every file was
  reviewed clean. A summary written by a person still carries muted and resolved threads as before, and
  the review falls back to a full one.
- **Size.** The memory gets at most 20,000 characters of the comment; a larger one is left out and the
  next run is a full review.

## Consequences

- A second push costs the system prompt, rules and requirements plus the changed files. On the
  evaluation cases, which are small, that saved 9% of input on average and up to 18%
  (eval/results/2026-10-18-incremental-saving.md); on a long pull request the unchanged files are a larger
  share and so is the saving.
- A token budget per pull request becomes possible, because the memory counts tokens across runs. The
  summary's footer shows the tokens of this run and of the pull request.
- Cost: the model no longer sees unchanged files, so a problem that only shows when a new change meets an
  old file it does not touch can be missed. The model can still open files in host mode; in the Action it
  sees the list of carried files. Setting `incremental = false` restores full reviews.
- Cost: a run with a personal token writes the summary as a user, so its memory is never trusted and
  every run is a full review.
- Cost: model text now sits in the state comment. `<` and `>` are escaped in the state JSON so it cannot
  close the comment it lives in.
- The Claude Code and Codex path (`bylaw context`, `bylaw post`) still reviews in full; it does not read
  the memory and writes none.

## Alternatives

- **Saved head is an ancestor of the new head, review the commits since.** Lost because rebases and
  force pushes, common on pull requests, make the saved head unreachable and force a full review, while
  file hashes keep what did not change.
- **Hunk-level carry-over inside a changed file.** Lost for now: line numbers shift and a hunk's meaning
  depends on its neighbours. A changed file is reviewed whole.
- **An HMAC over the memory.** Lost because the Action has no stable secret of its own; `GITHUB_TOKEN`
  changes every run. Trusting only bot-written summaries gives the same protection against read-only
  members.
