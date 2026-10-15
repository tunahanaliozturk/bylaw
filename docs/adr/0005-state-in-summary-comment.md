# 0005: Review state lives in the summary comment

Status: Accepted, 2026-10-15

## Context

On every push bylaw runs again. It needs to know which findings it already posted, which were fixed, and
which a person muted, otherwise it repeats itself and people stop reading it. The Action has no database
and bylaw has no hosted service.

## Decision

We keep the review state as hidden JSON inside the single summary comment and identify inline comments by
a fingerprint that excludes line numbers.

## Consequences

- No storage to run, pay for or secure. State travels with the pull request and disappears with it.
- Re-runs post only new findings, resolve threads whose fingerprint disappeared, and respect muted ones.
- Fingerprint stability under line shifts is covered by a unit test.
- Cost: anyone with write access can edit the summary comment and corrupt the state. bylaw treats
  unreadable state as empty and re-posts, which is noisy but never loses a finding.
- Cost: GitHub caps a comment at 65,536 characters, which limits how many muted fingerprints fit. State is
  compacted to hashes and the ceiling is documented.

## Alternatives

- **Hosted database.** Lost because it turns a free tool into a service someone must run. It would win for
  a GitHub App with cross-repository analytics.
- **Actions cache or artifacts.** Lost because caches expire and are scoped per branch, so state would
  vanish unpredictably. It would win if state had to survive a deleted summary comment.
