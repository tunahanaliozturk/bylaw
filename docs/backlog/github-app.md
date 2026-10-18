# GitHub App

Roadmap: Q3 in [ROADMAP.md](../ROADMAP.md). Target: v0.5. Item ids: `APP-n`.

One install for an organisation instead of a workflow file per repository.

**Done when** an organisation installs the app once and every chosen repository gets reviews with central settings.

## Items

- [x] **APP-1** (M) ADR: hosting model, key storage, what runs where. Done when: ADR accepted.
- [x] **APP-2** (S) App manifest with the narrowest permissions. Done when: manifest.
- [x] **APP-3** (L) Webhook receiver on the same core, with a queue and idempotency by head SHA. Done when: integration tests.
- [x] **APP-4** (M) Organisation defaults from the `.github` repository's `.bylaw.toml`. Done when: config tests.
- [ ] **APP-5** (M) Model key per installation in a secret store. Done when: docs and tests.
- [ ] **APP-6** (M) Container image and deployment guide. Done when: guide tested end to end.

## Notes

Needs a server, unlike the Action. [ADR 0017](../adr/0017-github-app.md) settles it: self-hosted only; a
hosted instance is out of scope until someone can operate it.
