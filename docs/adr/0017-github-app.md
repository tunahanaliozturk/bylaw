# 0017: bylaw as a self-hosted GitHub App

Status: Accepted, 2026-10-18. Refines 0005, 0008 and 0012 for the app; keeps 0004 and 0006.

## Context

The Action needs a workflow file and a model key secret in every repository. An organisation with sixty
repositories wants one install, one place for its settings and one place for its keys. A GitHub App gives
that: GitHub sends every pull request event of every chosen repository to one webhook, and the app reads
and comments with tokens it mints for itself.

An app needs a server, which bylaw has never had. The README and docs/privacy.md promise that bylaw has
no server and collects nothing, and ADR 0005 keeps state in the summary comment so that there is no
database to run. The questions are who runs that server, where its keys live, how it authenticates, what
a fixed identity changes about trust, and what an internet-facing webhook endpoint has to defend against.

## Decision

**Self-hosted only.** bylaw ships the app as code, a container image and a manifest. An organisation
registers its own GitHub App from the manifest and runs the server on its own infrastructure. A hosted
instance run by bylaw's authors is out of scope, for three reasons:

- It would hold every customer's code, model keys and tracker tokens in one place: a target worth
  attacking, guarded by one maintainer without an on-call rotation.
- It would end the privacy promise. Today nothing reaches bylaw's authors; a hosted app would see every
  diff it reviews, which needs a data processing agreement, a retention policy and a security programme.
- It needs billing or a free tier someone pays for, since every review is a model call.

A hosted instance can be reconsidered when there is demand and someone to operate it; the code would
not change, only who runs it.

**What runs where.**

- GitHub sends `pull_request` events to `POST /webhook` on your server.
- The server checks the signature, turns the delivery into a job keyed by repository, pull request and
  head commit, puts it on an in-process queue and answers `202` at once. GitHub counts a delivery as
  failed after ten seconds without an answer, and a review takes longer than that.
- A worker runs the same flow as `bylaw review --pr N --post` (`bylaw/pull_review.py`, shared with the
  CLI) with an installation token. Context, deterministic checks, model review, validation and
  publishing are the code the Action runs (ADR 0001).
- The model call goes from your server to the provider you choose, with the installation's key. Nothing
  goes to bylaw's authors.
- State stays in the summary comment (ADR 0005). The server keeps no database; its queue and its record
  of reviewed heads live in memory.

**How it authenticates.** The app's private key signs a JWT (RS256, issued 60 seconds in the past
against clock drift, expiring 9 minutes after now, under GitHub's 10 minute cap, with the client ID as
issuer). The JWT is used for exactly two calls: the app's own login at startup (`GET /app`) and minting
installation tokens. Each review mints a fresh token for **one repository** with **four permissions**:
`contents: read`, `issues: read`, `pull_requests: write` and `metadata: read`. Pull request write covers
the review, the summary comment on the pull request and resolving threads; contents stay read only, so a
token can never push code. A second token, for the owner's `.github` repository with `contents: read`
only, reads the organisation's defaults. GitHub's answer lists the repositories a token covers, and it
must name exactly the job's repository (compared without case) before the token is used, so a mix-up
between installations cannot send one repository's review through another's token. Tokens last an hour,
are never stored and never logged.

**Where the keys live.** The app's private key and webhook secret come from mounted files
(`BYLAW_APP_PRIVATE_KEY_FILE`, `BYLAW_WEBHOOK_SECRET_FILE`), or from the environment where files are not
possible. Model keys and tracker tokens are per installation, so each organisation on a shared server
pays for its own reviews: read on each review from a secret store, either variables named
`BYLAW_INSTALLATION_<id>_<NAME>` or a directory with one file per secret, `<dir>/<id>/<NAME>`, the way
Docker and Kubernetes mount secrets. Only the names bylaw reads are taken. A server-wide
`ANTHROPIC_API_KEY` is never used for an installation, so one organisation's key cannot review another's
code. An installation without a key gets the deterministic checks, as the Action does without one.

**Trust from a fixed identity.** ADR 0008 trusted any bot to carry bylaw's state, and ADR 0012 accepted a
bot-written summary as review memory, because a workflow token, an app and a personal token all post as
different accounts and an installation token cannot ask who it is. The app knows: it reads its slug from
`GET /app` at startup, and its comments are `<slug>[bot]`. So in the app, which ADR 0008's alternatives
said would win:

- the summary, its state and its review memory count only when the app's own login wrote them. Another
  bot's or a maintainer's comment with the summary marker is ignored and never edited;
- an inline comment's fingerprint marker counts as bylaw's own only from that login, or from an `OWNER`,
  `MEMBER` or `COLLABORATOR` as before, for maintainers' `bylaw: ignore`.

**Settings from the organisation.** `.bylaw.toml` on the default branch of the owner's `.github`
repository supplies defaults; the repository's base branch `.bylaw.toml` overrides them key by key. A
table such as `[jira]` counts as one key and is replaced whole, so a tracker site from one file never
pairs with an allow list from the other. ADR 0004 holds for both files: a pull request can change
neither, because one is read at the base commit and the other on the `.github` repository's default
branch. A pull request to the `.github` repository changes the defaults only once it merges. When the app
is not installed on `.github`, the review runs without defaults.

**Threat model for the webhook server.** It is reachable from the internet, so anyone can send it bytes.

- *Forged deliveries.* Every delivery must carry `X-Hub-Signature-256`, the HMAC-SHA256 of the raw body
  under the webhook secret. It is checked with a constant-time comparison before the body is parsed; a
  missing or wrong one gets `401` and nothing else happens. The SHA-1 header is not accepted. The server
  refuses to start without a secret.
- *Replay.* GitHub signs no timestamp, so a captured delivery stays valid. TLS keeps it from being
  captured. If one is replayed anyway, a head already reviewed or queued is a no-op, and a review always
  reads the pull request as it is now, so a replay can at most cause one more review of the current head;
  with incremental review (ADR 0012), a review of an unchanged pull request sends the model nothing. The
  delivery id is not used to reject repeats, because a redelivery from the app's settings keeps the same
  id, and that is how an operator retries a review that failed.
- *Size, slow senders and floods.* Bytes arrive before the signature can be checked, so the body is read
  up to 512 KiB and refused with `413` beyond that, and refused with `408` if it has not arrived within
  10 seconds. GitHub documents only a 25 MB cap on any payload; a `pull_request` delivery is tens of
  kilobytes, and its largest part, the pull request body of at most 65,536 characters, is 256 KiB even
  at four bytes a character (`BYLAW_APP_MAX_BODY` raises the limit). Uvicorn takes at most 64
  connections at once and closes idle keep-alive connections after 5 seconds. The proxy in front should
  set the same body limit and timeouts, so a slow or large request never reaches the server at all. At
  most 100 pull requests wait
  (`BYLAW_APP_MAX_PENDING`); past that the server answers `503` and GitHub marks the delivery failed. Two
  workers review at once (`BYLAW_APP_WORKERS`), one review per pull request at a time.
- *Malformed but signed input.* Repository names are checked against GitHub's character set and may not
  contain dot segments, head commits must be hex. Anything else is `400`.
- *Code execution.* bylaw never checks out or runs repository code. It reads the diff and files through
  the API. Configuration is TOML and YAML read with safe loaders; JavaScript ESLint configs stay text.
- *Fork pull requests.* The app sees a fork's pull request through the base repository's API with its
  own token, so there is no `pull_request` versus `pull_request_target` choice to make (ADR 0006). The
  rule that matters still holds: secrets must not reach untrusted code, and since no pull request code
  runs, the model key and the token stay inside the server process. Prompt injection from fork text is
  handled as before: text is data, findings must pass the validator, and the token can only comment.
- *Logs.* Keys, tokens and the webhook secret are never logged and the settings hide them in their repr.
  Text from a pull request or the model is flattened to one line, so it cannot forge log lines.

**Queue limits.** The queue is in process. A pull request has at most one job waiting: a later delivery
replaces it, even a redelivered older one, because the review reads the pull request as it is when it
starts, not the head the event named. The head the review read counts as reviewed, as does the one the
event named, and a head already reviewed is not reviewed again. Nothing survives a restart: an event that arrives while the
server is down, or waits in the queue when it stops, is picked up by the pull request's next push, or by
redelivering it from the app's advanced settings. A durable queue can come later without changing the
review.

## Consequences

- One install covers an organisation; repositories need no workflow file and no secret.
- The Action, the CLI and the plugin are unchanged and pull in no web stack: the server's dependencies
  (Starlette, Uvicorn, PyJWT with cryptography) are the optional `app` extra.
- A summary written by anyone but the app no longer carries state or memory in app mode, which closes the
  read-only member gap ADR 0012 describes for good, and other bots on the repository cannot plant state.
- Cost: there is a server to run, patch and watch. The deployment guide keeps it to one container with a
  health check.
- Cost: an installation token covers one repository, so issues in other private repositories listed in
  `issue_repos` are noted as unreadable, as they are for the Action's `GITHUB_TOKEN`.
- Cost: a configuration error or a failed review shows only in the server log; there is no failing
  check run as in the Action.
- Cost: the in-memory record of reviewed heads is lost on restart, so the first redelivery after a
  restart reviews again. State in the summary keeps that from repeating comments.
- Cost: moving from the Action to the app changes bylaw's account, so the first app review cannot read
  the Action's summary or recognise the Action's inline comments as its own. It starts a new summary
  and a full review and may repeat findings the Action already posted; remove the workflow before
  installing the app on a repository with open pull requests to keep that to one round.

## Alternatives

- **A hosted instance.** Lost for the reasons above. It would win once someone can operate it with the
  security and privacy work that implies.
- **Keep the Action and template the workflow file.** Lost because settings and keys still live in every
  repository. It still wins for a single repository, and it stays the default in the README.
- **A durable queue (Redis, SQS, a database).** Lost for now: it adds a service to run, and the missed
  review it prevents is picked up by the next push. It would win for organisations with many pull
  requests per minute or long outages.
- **One token per installation covering all its repositories.** Lost because a token that can read
  every repository is a bigger loss if a bug or a log ever leaks it.
- **A serverless function per delivery.** Lost because a review takes longer than many function time
  limits and the queue's idempotency needs one process to own it. It would win with a durable queue in
  front.
- **An HMAC over the summary state.** Not needed now: with a fixed identity, trusting only the app's own
  login gives the same protection without a key to rotate.
