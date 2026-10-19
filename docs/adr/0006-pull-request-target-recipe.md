# 0006: pull_request_target recipe for fork pull requests

Status: Accepted, 2026-10-15

## Context

Open source projects receive most pull requests from forks. On the `pull_request` event, GitHub gives fork
pull requests no secrets and a read-only token, so bylaw can neither call a model nor post a comment.
`pull_request_target` runs with secrets and a write token, which is dangerous when the workflow checks out
and runs the pull request's code.

## Decision

We support fork pull requests through a documented `pull_request_target` workflow that never checks out
the pull request head, with an optional `labeled` trigger so maintainers choose which fork pull requests
get reviewed.

## Consequences

- bylaw reads the diff through the API and the rules from the base branch and never executes pull request
  code, so the main risk of `pull_request_target` does not apply to bylaw itself.
- On plain `pull_request` from a fork, bylaw prints a notice and exits with success instead of failing.
- The label gate stops a flood of fork pull requests from spending the maintainer's API budget.
- Cost: a maintainer who adds `actions/checkout` of the head ref to this workflow reopens the risk. The
  README warns against it in the recipe itself.
- Cost: text in a fork pull request can still try prompt injection. The token can only comment, and
  injected output still has to pass the validator.

## Alternatives

- **Same-repository pull requests only.** Lost because most open source contributions come from forks.
  It would win for private repositories, which can keep using `pull_request`.
- **`workflow_run` two-stage pattern** (unprivileged job produces an artifact, privileged job posts).
  Lost because bylaw needs the secret in the stage that calls the model, so the split adds complexity
  without removing the secret from a privileged context.

## Amendment, 2026-10-19: queue runs, do not cancel them

The 1.0 security review found that the recipe's `cancel-in-progress: true` let a fork author spend past
`[budget] pr_tokens`. The label stays on for later pushes, so every push starts a run, and each push
cancelled the run before it. A cancelled run has already called the model but never writes its tokens
to the summary, so the next run counted from the same total and the budget never moved.

The recipe now sets `cancel-in-progress: false`. A run in progress always finishes and records what it
used; GitHub keeps at most one pending run per group and drops the older pending one, which has not
spent anything yet. The recipe's header shows `[budget] pr_tokens`, because with the label on, the fork
author decides how often bylaw runs.

- Cost: a burst of pushes waits for the review in progress before the newest one is read, instead of
  starting at once.
- The same-repository recipe keeps `cancel-in-progress: true`: its authors have write access and could
  change the workflow anyway.

