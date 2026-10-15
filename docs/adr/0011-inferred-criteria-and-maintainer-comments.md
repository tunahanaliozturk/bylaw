# 0011: Infer criteria for prose requirements, and read maintainers' issue comments

Status: Accepted, 2026-10-15

## Context

Requirement traceability is bylaw's main difference from other reviewers, but it only worked when an issue had a checklist or an "Acceptance criteria" heading. Most issues are written as a paragraph, and the details often land later in the comments ("also, it has to be reversible for 30 days"). Those pull requests got a summary with nothing to check.

## Decision

- For a linked issue with no structured criteria, the brief asks the reviewer to derive at most five testable criteria from its text, in the same review call, labelled `<source>/IC-1` to `IC-5`, each with its text. For an issue that has a checklist and maintainer comments, it asks for up to five more from the comments, covering what the list misses. Validation keeps an `IC-` result only for such an issue, only with text of at most 300 characters, and at most five. A requirement finding may cite a kept one. The summary lists them after the listed criteria and marks them "(inferred)".
- Spec files are not inferred from: a prose ADR or design note changed by a pull request is context, and asking for five rows per file would flood documentation changes.
- When bylaw reads a linked issue, it also reads all its comments and keeps those by `OWNER`, `MEMBER` and `COLLABORATOR` authors, never bots and never the pull request's own author, newest first within 20 comments and 8,000 characters; a single comment longer than what is left is skipped, not allowed to push the others out. They are appended to the requirement text under "Comments from maintainers".
- Structured criteria are still extracted from the issue body only.

## Consequences

- A prose issue now gets a checklist, and a maintainer's later clarification counts.
- Inferred criteria come from the model, so they vary between runs and between models. The "(inferred)" mark tells readers that, and their keys are not stable across runs; a thread on an inferred criterion may not match on the next run.
- Someone outside the project, or the pull request's own author, cannot change what the pull request is checked against by commenting on its issue, for the same reasons as ADR 0008.
- Criteria keys from the body stay stable when the discussion grows, because comments never add `AC-` items.
- At least one more API call per linked issue (one per 100 comments).

## Alternatives

- **A separate model call that extracts criteria first.** Lost because it doubles the paid calls for every prose requirement, and the Claude Code and Codex path would need a second step. It would win if inferred criteria had to be identical across runs.
- **Ask users to write checklists.** Lost because most issues are prose and bylaw should work with the repository as it is.
- **All issue comments.** Lost because anyone can comment on a public issue, including the pull request author.
