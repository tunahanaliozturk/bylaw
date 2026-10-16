---
description: Review a pull request or branch against the repository's own rules and linked requirements with bylaw
argument-hint: "[pr-number | #pr | pull request URL | base-branch] [post]"
---

Use the bylaw-review skill to review this target: $ARGUMENTS

First run `gh repo view --json nameWithOwner,defaultBranchRef`. It gives the repository as `owner/name` and its default branch; on a fork it is the repository the fork came from, not `origin`. Without the GitHub CLI, ask the user for `owner/name`.

Read the arguments like this:

- A number, `#12`, or a pull request URL means that pull request. For a URL, use the `owner/name` and number in it.
- `post` is never a branch name: it means post the review to the pull request. `post` alone, or `post` with a branch and no pull request, cannot post anywhere; say so and show the review instead.
- Any other word is the base branch for a local review of the current branch.
- With no target, compare the current branch with the default branch from `gh repo view` (often `main`, sometimes `master`).

Show the review with `bylaw post --dry-run`, and post it with `--pr` only when the arguments include `post` and name a pull request.
