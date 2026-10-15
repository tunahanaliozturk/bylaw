---
description: Review a pull request or branch against the repository's own rules and linked requirements with bylaw
argument-hint: "[pr-number | base-branch] [post]"
---

Use the bylaw-review skill to review this target: $ARGUMENTS

A number means a pull request in the current repository (find `owner/name` from `git remote get-url origin`). Anything else means a local branch compared with that base; with no argument, compare the current branch with `main`. Show the review with `bylaw post --dry-run`, and post it with `--pr` only if the arguments include `post`.
