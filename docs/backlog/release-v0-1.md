# v0.1.0 release

Roadmap: Q1 (M6) in [ROADMAP.md](../ROADMAP.md). Target: v0.1.0. Item ids: `REL-n`.

Get bylaw into people's hands with numbers behind every claim: a measured evaluation, real screenshots, and installs that work from a clean machine.

**Done when** `uvx bylaw` and `uses: tunahanaliozturk/bylaw@v0` work from a clean machine, and the README quotes a committed evaluation run.

## Items

- [x] **REL-1** (M) First paid evaluation run with the Action's default model, `claude-opus-5-5`. Done when: cost per case measured on `--only py-sqli`, then the full set; `eval/results/<date>-opus-5-5/` committed.
- [x] **REL-2** (M) Host evaluation runs with Claude Code and Codex through `bylaw eval prepare` and `--answers`. Done when: both reports committed next to the API run.
- [x] **REL-3** (S) README results table from REL-1 and REL-2. Done when: every number links to its report.
- [x] **REL-4** (S) Live Action run on `bylaw-demo` with the `ANTHROPIC_API_KEY` secret. Done when: a demo pull request gets model findings, inline comments and the summary.
- [x] **REL-5** (M) Real screenshots of `bylaw-demo` pull requests, taken by a script in `tools/`. Done when: inline security finding, suggestion block, summary with criteria and terminal output in `docs/images/`.
- [x] **REL-6** (S) Social preview card from the seal logo. Done when: 1280x640 PNG set in the repository settings.
- [x] **REL-7** (M) PyPI trusted publishing on a version tag. Done when: `uvx bylaw --version` works on a machine without the repository.
- [x] **REL-8** (S) `v0.1.0` tag, the moving `v0` tag and release notes from the changelog. Done when: the recipes work with `@v0`.
- [x] **REL-9** (S) GitHub Marketplace listing for the Action. Done when: listed and installable from the Marketplace.
- [ ] **REL-10** (S) Claude plugin directory listing. Done when: the listing is live. Submitted 2026-10-17 from `plugin/` on main, held for one reviewer check (the skill passes the GitHub CLI token to the GitHub API). The OpenAI plugin directory is left out for now: it needs a government-ID identity check of the publisher. Codex users install from this repository's marketplace (`codex plugin marketplace add tunahanaliozturk/bylaw`).
- [x] **REL-11** (S) Skill and docs move from `git+` to `uvx bylaw==<version>`. Done when: no doc tells users to run `main`.
- [ ] **REL-12** (S) Launch post with the evaluation as the story. Done when: Show HN and the Claude Code and Codex communities.

## Notes

REL-1 and REL-4 spend money on a model: they wait for an approved budget and a key set by the owner.
