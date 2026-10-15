# 0009: The Action runs bylaw from its own source with the lock file

Status: Accepted, 2026-10-15

## Context

ADR 0002 planned a composite action that runs `uvx bylaw@<version>` from PyPI. bylaw is not on PyPI
yet, and a PyPI install resolves dependency ranges at run time, so an upstream release could change
behaviour under a pinned bylaw tag. When a workflow uses `tunahanaliozturk/bylaw@v0`, the runner has
already checked out the action's repository at that tag, lock file included.

## Decision

We run `uv run --project "$GITHUB_ACTION_PATH" --locked --no-dev bylaw ...`, so the Action uses the
code and the exact dependency versions of the tag the workflow names.

## Consequences

- An action tag is a reproducible release: same code, same locked dependencies.
- The Action works before any PyPI release, which lets M3 be checked end to end now.
- Cost: each run creates a virtual environment from the lock, a few seconds with uv's cache and longer
  on a cold runner. To be measured on the demo repository and reported.
- Cost: the environment is created inside the action directory on the runner; that directory is
  throwaway, so nothing persists between runs.

## Alternatives

- **`uvx bylaw@<version>` from PyPI.** Lost for now because it needs a release first and resolves
  dependencies at run time. It would win for users who want one install shared between the Action and
  their terminal; the CLI will still be published there in M6.
- **Docker action.** Lost because it runs only on Linux runners and pulls an image on every run. It
  would win if bylaw needed system packages beyond Python.
