# GitHub App

Roadmap: Q3 in [ROADMAP.md](../ROADMAP.md). Target: v0.5. Item ids: `APP-n`.

One install for an organisation instead of a workflow file per repository.

**Done when** an organisation installs the app once and every chosen repository gets reviews with central settings.

## Items

- [x] **APP-1** (M) ADR: hosting model, key storage, what runs where. Done when: ADR accepted.
- [x] **APP-2** (S) App manifest with the narrowest permissions. Done when: manifest.
- [x] **APP-3** (L) Webhook receiver on the same core, with a queue and idempotency by head SHA. Done when: integration tests.
- [x] **APP-4** (M) Organisation defaults from the `.github` repository's `.bylaw.toml`. Done when: config tests.
- [x] **APP-5** (M) Model key per installation in a secret store. Done when: docs and tests.
- [x] **APP-6** (M) Container image and deployment guide. Done when: guide tested end to end.

## Notes

Needs a server, unlike the Action. [ADR 0017](../adr/0017-github-app.md) settles it: self-hosted only; a
hosted instance is out of scope until someone can operate it.

APP-6 was tested end to end locally, not against GitHub. On 18 October 2026 `tools/app_smoke.py` ran the
whole review both as a local process and as the built image (293 MB, user 10001): Docker reported the
container healthy, the signed delivery got `202` and a forged one `401`, and the fake GitHub received the
summary and one inline comment from `bylaw-acme[bot]`. A real registration needs a maintainer's account,
so the checks below stay open until someone runs them.

## Live checks before v1.0

With a real app registered from `docs/app/manifest.json` on a test organisation, the server reachable
over HTTPS, and a test repository with a `.editorconfig` that trims trailing whitespace:

- [ ] Registration through `docs/app/register.html` creates the app with exactly pull requests write,
  contents read, issues read and metadata read, and the pull request event; the conversion call returns
  the client ID, the private key and the webhook secret.
- [ ] GitHub's `ping` on creation gets `200`, and the app's **Recent deliveries** shows it green.
- [ ] Opening a pull request with trailing whitespace gets a summary comment from `<slug>[bot]` within a
  minute; the delivery shows `202`.
- [ ] The installation token can post the summary comment with issues read and pull requests write only,
  as the permissions page says the issue comment endpoints accept either permission. If it gets `403`,
  the manifest needs issues write.
- [ ] Resolving a thread through GraphQL (`resolveReviewThread`) works with pull requests write: push a
  fix for an inline finding and check that its thread is resolved.
- [ ] `GET /app` returns the slug, and GraphQL names the bot's comments `<slug>` without `[bot]`, which
  the login comparison assumes: a second push edits the same summary instead of posting a new one.
- [ ] A fork pull request gets bylaw's own checks and the note explaining why, with no workflow and no
  secret on the fork; adding the configured `model_review_label` delivers `labeled` and the review runs
  again with the model.
- [ ] With the app installed on `.github` and a `.bylaw.toml` there, its settings apply; without the app on
  `.github`, the token request for it fails with `422` (or `404`) and the review runs without defaults.
- [ ] Redelivering a delivery from **Advanced** settings answers `202` with `duplicate` and posts nothing;
  pushing a new commit reviews again and edits the same summary.
- [ ] A delivery with a wrong secret (change it in the app settings) is answered `401`.
- [ ] `docker ps` shows the container `healthy`, and a restart during a review loses at most that review,
  which the next push or a redelivery brings back.
- [ ] The access token answer lists `repositories` with each `full_name` when the request names them;
  the app refuses a token whose answer does not name exactly the job's repository.
- [ ] An installation token minted in the new stateless `ghs_` format works (GitHub began rolling it out in
  April 2026; bylaw treats tokens as opaque strings).
