# 0004: Rules and configuration come from the base branch

Status: Accepted, 2026-10-15

## Context

bylaw reviews a pull request against `.editorconfig`, linter configuration, `CONTRIBUTING.md` and its own
`.bylaw.toml`. If those files were read from the pull request head, the pull request could relax the rules
it is being reviewed against, deliberately or not, and pass a review it should fail.

## Decision

We read every rule source and `.bylaw.toml` from the base branch commit the pull request targets.

## Consequences

- A pull request cannot loosen its own review. A test edits `.bylaw.toml` in a pull request and asserts
  the base version is used.
- Cost: a pull request that legitimately changes a rule is reviewed against the old rule until it merges.
  The summary comment says so when it sees rule files in the diff.
- Requirement specs that are new in the pull request are still read from the head, because a spec added
  alongside its implementation is normal. Specs are evidence for traceability, not rules that grant
  permission.

## Alternatives

- **Read everything from the head.** Lost because it lets a pull request disable checks on itself. It would
  win only in a single trusted author repository.
- **Merge base and head rules.** Lost because the result is hard to explain in a comment and still lets a
  pull request add exceptions for itself.
