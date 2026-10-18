# Agent instructions

This repository holds two Python packages that ship separately, `packages/api` and `packages/worker`. Each has an `AGENTS.md` of its own; follow the one closest to the file you change.

## Everywhere

- Public functions have type hints on every argument and the return value.
- Use the `logging` module for messages, never `print`.
