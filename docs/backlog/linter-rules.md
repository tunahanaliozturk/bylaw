# Linter configuration as structured rules

Roadmap: Q2 in [ROADMAP.md](../ROADMAP.md). Target: v0.3. Item ids: `LNT-n`.

Read which rules a team's linters enforce, so findings cite a rule id (`ruff:S608`) and the model knows what the team cares about. bylaw still never runs the linters itself.

**Done when** a finding can cite a rule id that exists in the repository's linter configuration, and validation checks it.

## Items

- [x] **LNT-1** (M) Ruff: enabled rule codes and per-file ignores from `pyproject.toml` and `ruff.toml`. Done when: parsed rules in the context.
- [x] **LNT-2** (M) ESLint JSON and YAML configs; flat configs in JavaScript stay prose. Done when: rules listed for JSON and YAML.
- [x] **LNT-3** (S) golangci-lint: enabled linters from `.golangci.yml`. Done when: parsed list.
- [x] **LNT-4** (M) .NET analyzers: `dotnet_diagnostic` severities in `.editorconfig` and the analysis level. Done when: parsed list.
- [x] **LNT-5** (M) Findings cite `<tool>:<rule id>`; validation drops ids the configuration does not enable. Done when: validate tests.
- [ ] **LNT-6** (S) Evaluation cases that need a rule id citation. Done when: cases in the set.

## Notes

Configuration written as code (for example `eslint.config.js`) is never executed; it stays prose.
