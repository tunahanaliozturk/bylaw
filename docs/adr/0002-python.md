# 0002: Python, distributed with uvx

Status: Accepted, 2026-10-15

## Context

Most users will install bylaw as a GitHub Action, so start-up cost per pull request matters. Claude Code
and Codex users need to run it from a terminal without a manual install. The author's existing Python
house standard (lint, typing, tests, licence audit) is ready to reuse, and the evaluation work is easier
in Python.

## Decision

We write bylaw in Python and distribute it through PyPI, run with `uvx bylaw`.

## Consequences

- The house standard and tooling apply as they are, which shortens M1.
- Evaluation and data handling stay in one language.
- Cost: GitHub has no native Python action runtime. The Action is a composite action that installs `uv`
  and runs `uvx`, which adds roughly 5 to 15 seconds per run compared with a JavaScript action. This is to
  be measured in M3 and reported.
- Cost: local users need `uv` installed, which is less common than Node, especially on Windows. The README
  names the one-line install.

## Alternatives

- **TypeScript.** A native JavaScript action starts in about a second, the official `@actions/*` packages
  are first class, and `npx` works wherever Claude Code or Codex is installed. Lost on author speed and on
  evaluation tooling. It would win if start-up time turned out to be the main complaint from users.
- **Go.** A single static binary with no runtime. Lost because the LLM SDKs and evaluation tooling are
  thinner and a binary per platform has to be built and published. It would win if bylaw had to run in
  locked-down environments with no package manager.
