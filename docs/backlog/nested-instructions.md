# Nested instructions in monorepos

Roadmap: Q2 in [ROADMAP.md](../ROADMAP.md). Target: v0.3. Item ids: `NST-n`.

In a monorepo each package often has its own `AGENTS.md`, `CONTRIBUTING.md` or `.editorconfig`. The closest one should apply to each changed file.

**Done when** a change in `packages/api/` is reviewed against `packages/api/AGENTS.md` and the root rules, and the brief says which applies where.

## Items

- [x] **NST-1** (M) Collect instruction files at every directory level above the changed files, from the base branch. Done when: context test. Done differently (ADR 0013): every level above a changed file is searched, but for each file name only the nearest one is read in, because a nearer `AGENTS.md` replaces a farther one.
- [x] **NST-2** (M) Nearest file wins; the brief groups rules by directory. Done when: prompt test.
- [x] **NST-3** (S) Validation accepts evidence paths in subdirectories. Done when: validate test.
- [x] **NST-4** (M) Evaluation project with two packages whose rules conflict. Done when: cases in the set.

## Notes

Only directories that hold changed files are read, to keep the prompt small.
