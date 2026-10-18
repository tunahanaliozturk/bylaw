# 0013: Package rules come from the nearest directory, linter rule ids are parsed as data

Status: Accepted, 2026-10-18. Builds on 0004.

## Context

Until now bylaw read rule files only at the repository root. In a monorepo each package often has its own
`AGENTS.md`, `CONTRIBUTING.md` or linter configuration, and two packages can ask for opposite things: an API
package that must return errors as values and a worker that must raise so its queue retries. A change in
`packages/api/` was reviewed against the root rules alone, and nothing stopped a finding from citing the
worker's rule against API code.

Linter configuration reached the reviewer as line-numbered text. A finding could cite `ruff.toml:4`, the
line that says `select = ["E", "S"]`, which tells a reader little, and the validator could only check that
the line exists, not that the rule behind the finding is one the team turned on. Teams talk about rule ids
(`S608`, `no-console`), and a reviewer that cites them is easier to trust.

Three limits shape both answers: the brief must not grow with the size of the repository, each file read
from GitHub is an API call, and bylaw never runs repository code, because the pull request is untrusted
(ADR 0004, 0006).

## Decision

**Which package files.** For each changed file and each of `AGENTS.md`, `CLAUDE.md`, `CONTRIBUTING.md` and
the linter files of the file's language, the nearest directory above it on the base branch that holds that
file supplies it. The root rules are read as before. Directories without changed files are never read, and
a farther file of the same name that is nearest to no changed file is left out. A `pyproject.toml` without
`[tool.ruff]` does not count, so the search goes further up, as Ruff's own does.

**How they are found.** Sources gain `list_base(directory)`. GitHub answers it from the recursive base tree,
read once per review and already used for moved files; when GitHub truncates that tree, one contents
listing per directory. Local git uses `git ls-tree`. At most 40 directories are looked in, those nearest
the root first, and the summary notes the rest.

**Where each rule applies.** Every rule source names its directory, `""` for the whole repository. Once a
package has rules of its own, the brief groups the rules by directory, names the changed files under each
group, and tells the reviewer that the nearest directory wins and another package's rules never apply. A
repository without package rules gets the same brief as before. Validation drops a finding that cites a
rule line of a directory its file is not in.

**Linter rule ids.** Each linter file is parsed as data into the ids it turns on and off, overall and per
file glob, plus notes for what cannot become ids:

- Ruff, from `ruff.toml`, `.ruff.toml` and `pyproject.toml`: `select`, `extend-select`, `ignore` and the
  per-file ignores, in the `lint` table or at the top level. Selectors are prefixes and the most specific
  one wins, as in Ruff; with no `select`, Ruff's default set. An `extend` is noted, not followed.
- ESLint, from `.eslintrc.json` (comments allowed) and `.eslintrc.yml`/`.yaml`: `rules` and `overrides`.
  An `extends` is noted, not followed. `eslint.config.js` and the other JavaScript files stay text.
- golangci-lint, from `.golangci.yml`/`.yaml`: version 1 `enable`, `disable`, `enable-all`, `disable-all`
  over the default set, and version 2 `linters.default`.
- .NET: `dotnet_diagnostic.<id>.severity` in `.editorconfig` sections and in `.globalconfig`, with
  `error`, `warning` and `suggestion` on and `none` and `silent` off. `AnalysisLevel` and `AnalysisMode`
  from `Directory.Build.props` become a note.

A file that does not parse stays text and the summary says its ids cannot be cited. YAML goes through
`ruamel.yaml`'s safe loader, which builds only plain data.

**Citing an id.** Evidence may read `<tool>:<id>` (`ruff:S608`, `eslint:no-console`,
`golangci-lint:gosec`, `dotnet:CA2100`). The brief lists the ids under each configuration. Validation takes
the configurations of that tool whose directory holds the finding's file, nearest first, and the first one
that says anything about the id decides. Ruff reads only its nearest configuration, so for Ruff that one
always decides. An id no covering configuration turns on is dropped with the finding.

## Consequences

- The brief grows by the rule files nearest to the changed files and nothing else. An evaluation project
  with two packages whose rules conflict measures whether the reviewer follows the nearest one.
- One more GitHub call per review that touches a subdirectory, for the base tree; up to 40 on a repository
  so large that GitHub truncates it.
- Only ids written in the configuration can be cited. Rules that arrive through an ESLint `extends`, the
  golangci-lint `fast` set or the .NET analysis level are not known, so a finding that cites one is
  dropped even though the linter would report it. The notes in the brief say so, and the configuration
  line can still be cited.
- Not modelled: ESLint's `root: true`, Ruff's `extend` chain, golangci-lint's exclusion rules (regular
  expressions over paths), and the small differences between each tool's glob dialect and the
  `.editorconfig` globs used for all of them.
- Validation cannot see that a root rule and a package rule conflict, so a finding that cites the root
  rule against a package that says the opposite is kept. Telling the reviewer that the nearest directory
  wins is what handles that case.
- The incremental review key (ADR 0012) still hashes each rule's path and text. Directories and ids are
  derived from those, so saved memories stay valid, and an edit to a package rule file forces a full
  review like an edit to a root one.
- A new dependency, `ruamel.yaml` (MIT, pure Python).

## Alternatives

- **Every instruction file in the repository.** Lost because the brief would grow with the repository,
  not with the change.
- **Every level above a changed file, not only the nearest.** Lost because a nearer file of the same name
  is there to replace the farther one, which is how `AGENTS.md` is meant to work, and both would cost
  prompt space for rules that do not apply.
- **Reading each candidate name directly, without a listing.** Lost because it is about fifteen names per
  directory, each a GitHub call, where the tree costs one call per review.
- **Asking the linters for their effective settings** (`ruff check --show-settings`,
  `eslint --print-config`). Lost because it runs repository code: ESLint configs and plugins are
  JavaScript. It would win in a local mode on a trusted checkout.
- **A catalogue of every tool's rule ids and presets.** Lost because it is large and stale after every
  linter release. It would win if dropped `extends` citations turn out to be common.
- **Accepting any well-formed id.** Lost because the point is to stop a reviewer citing rules the team
  does not enforce.
- **PyYAML.** Lost because it has no wheel for Python 3.15, which CI runs, and building it needs a C
  compiler.
