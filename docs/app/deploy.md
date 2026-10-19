# Running bylaw as a GitHub App

The Action needs a workflow file and a key in every repository. The app needs one install: GitHub sends
the pull request events of every repository you choose to one server, and that server reviews them with
the same code the Action runs. You register the app under your own organisation and run the server
yourself; there is no hosted bylaw, so your code and keys stay with you ([ADR 0017](../adr/0017-github-app.md)
says why).

What you need:

- A host GitHub can reach over HTTPS, with Docker, or Python 3.13 or later and [uv](https://docs.astral.sh/uv/).
- A model key for each organisation that should get model reviews. Without one, an installation gets
  the deterministic checks only, as the Action does without a key.

## 1. Register the app

The manifest in [manifest.json](manifest.json) holds everything GitHub needs: the name, the webhook, four
permissions and one event. Registering from it takes a minute and avoids clicking through the settings by
hand.

1. Open [register.html](register.html) from your clone in a browser. Fill in your organisation, a name
   for the app (it must be unique on GitHub, such as `bylaw-acme`) and your server's webhook URL, which
   ends in `/webhook`. Press the button.
2. GitHub shows the app it will create. Confirm.
3. GitHub sends you to `http://localhost:8000/registered?code=...`. Nothing needs to listen there: the page
   fails to load, and the code is in the address bar. Exchange it within an hour:

   ```
   curl -X POST https://api.github.com/app-manifests/<code>/conversions > app.json
   jq -r .pem app.json > app.pem
   jq -r .webhook_secret app.json > webhook-secret
   jq -r '.client_id, .slug' app.json
   rm app.json
   ```

   Keep `app.pem` and `webhook-secret` where only the server can read them; they are the app's
   identity. The answer also holds an OAuth client secret, which bylaw does not use; deleting `app.json`
   discards it.

The manifest keeps the app private (`"public": false`), so only your organisation can install it.

To register by hand instead, create a GitHub App under your organisation's developer settings with the
webhook URL, a random webhook secret, the permissions below and the **Pull request** event, then
generate a private key.

| Permission | Access | Why |
| --- | --- | --- |
| Pull requests | Read and write | Read the pull request, its files and commits; post the review, the summary comment on the pull request, and resolve threads. |
| Contents | Read | Read rule files, ADRs and `.bylaw.toml` at the base commit, and the organisation's `.github/.bylaw.toml`. |
| Issues | Read | Read the issues a pull request closes and their maintainers' comments. |
| Metadata | Read | Required by GitHub for every app. |

The app never asks for write access to contents, so it cannot push code. It subscribes only to
`pull_request` and reviews on `opened`, `synchronize`, `reopened` and `ready_for_review`, the same
actions as the Action's workflow; every other action is answered and ignored.

## 2. Run the server

With Docker, from the repository root:

```
docker build -t bylaw-app .
docker run -d --name bylaw-app --restart unless-stopped --stop-timeout 120 -p 127.0.0.1:8000:8000 \
  -v /srv/bylaw/secrets:/run/secrets:ro \
  -e BYLAW_APP_CLIENT_ID=Iv23liExample \
  -e BYLAW_APP_PRIVATE_KEY_FILE=/run/secrets/app.pem \
  -e BYLAW_WEBHOOK_SECRET_FILE=/run/secrets/webhook-secret \
  -e BYLAW_SECRETS_DIR=/run/secrets/installations \
  bylaw-app
```

The image runs as an unprivileged user, holds only the locked runtime dependencies, and checks its own
health endpoint with Python, since the slim base image has no curl. `docker ps` shows it as `healthy`
once it answers.

Without Docker:

```
uv sync --locked --no-dev --extra app
BYLAW_APP_CLIENT_ID=... BYLAW_APP_PRIVATE_KEY_FILE=... BYLAW_WEBHOOK_SECRET_FILE=... uv run --no-dev --extra app bylaw-app
```

The server speaks plain HTTP on port 8000. Put a reverse proxy that terminates TLS in front of it (Caddy,
nginx, your cloud's load balancer) and point the webhook URL at the proxy: GitHub should deliver over
HTTPS, and a webhook secret proves who sent a delivery but does not hide it.

Anyone on the internet can send the endpoint bytes before the signature is checked, so let the proxy turn
away what GitHub never sends: bodies over 512 KiB and requests that trickle in. In nginx that is
`client_max_body_size 512k;`, `client_body_timeout 10s;` and `client_header_timeout 10s;`; in Caddy,
`request_body { max_size 512KB }` with `servers { timeouts { read_body 10s } }`. The server enforces the same
limits itself (512 KiB, 10 seconds for the body, at most 64 connections, idle keep-alive closed after
5 seconds), but a proxy stops them before they take a connection.

Settings, all from the environment:

| Variable | Default | Meaning |
| --- | --- | --- |
| `BYLAW_APP_CLIENT_ID` | required | The app's client ID (recommended by GitHub) or numeric app ID. |
| `BYLAW_APP_PRIVATE_KEY_FILE` | required | Path to the app's private key. `BYLAW_APP_PRIVATE_KEY` holds the PEM itself where files are not possible. |
| `BYLAW_WEBHOOK_SECRET_FILE` | required | Path to the webhook secret. `BYLAW_WEBHOOK_SECRET` holds it directly. |
| `BYLAW_SECRETS_DIR` | unset | Folder with one subfolder per installation for model keys and tracker tokens; unset reads them from the environment instead (section 5). |
| `BYLAW_PROVIDER` | `anthropic` | `anthropic` or `openai`, for every installation. The cloud providers and local servers in [providers.md](../providers.md) are not offered: they sign in with the server's own credentials, which every installation would share. |
| `BYLAW_MODEL`, `BYLAW_EFFORT` | provider default | As `--model` and `--effort` for `bylaw review`. |
| `BYLAW_APP_WORKERS` | `2` | Pull requests reviewed at once. |
| `BYLAW_APP_MAX_PENDING` | `100` | Pull requests that may wait; beyond that, deliveries get `503`. |
| `BYLAW_APP_MAX_PENDING_PER_INSTALLATION` | `20` | Of those, how many may come from one installation, so one organisation cannot fill the queue. |
| `BYLAW_APP_MAX_BODY` | `524288` | Largest delivery read, in bytes; larger ones get `413`. |
| `BYLAW_APP_HOST`, `PORT` | `127.0.0.1`, `8000` | Where the server listens. The image sets the host to `0.0.0.0`. |
| `GITHUB_API_URL`, `GITHUB_GRAPHQL_URL` | `https://api.github.com` | For GitHub Enterprise Server. |

Prefer the `_FILE` variables: a value in the environment shows up in `docker inspect` and in process
listings.

## 3. Install the app

In the app's settings, choose **Install App**, pick your organisation and choose the repositories. Include
the organisation's `.github` repository if you want organisation defaults (next section): the app only
reads `.bylaw.toml` there. Every pull request opened or pushed to after that gets a review.

If a repository already runs the bylaw Action, remove its workflow first. The app posts as its own
account, so it does not recognise the Action's summary or inline comments and starts afresh; on a pull
request both had reviewed, findings the Action already posted appear once more.

## 4. Organisation defaults

A `.bylaw.toml` on the default branch of the organisation's `.github` repository sets defaults for every
repository the app reviews. A repository's own `.bylaw.toml`, read from the pull request's base branch as
always, overrides them key by key:

```toml
# acme/.github, .bylaw.toml
severity_threshold = "high"
max_comments = 10
[jira]
url = "https://acme.atlassian.net"
projects = ["ACME"]
```

```toml
# acme/payments, .bylaw.toml on main
max_comments = 25
```

A pull request to `acme/payments` is reviewed with `severity_threshold = "high"`, `max_comments = 25` and
the organisation's `[jira]` table. A table counts as one key: a repository that sets `[jira]` replaces the
whole table, so its site never pairs with the organisation's project list. Neither file can be changed by
the pull request under review: one is read at its base commit, the other on the `.github` repository's
default branch, so a change to the defaults takes effect once it merges there. When the app is not
installed on `.github`, or the file does not exist, there are no defaults. An invalid defaults file stops
the review with an error in the server log naming that file.

`profiles` is the one key that is not overridden: a repository's compliance profiles add to the
organisation's, so `profiles = ["iso27001"]` in the defaults reaches every repository and none can drop it
([compliance.md](../compliance.md), [ADR 0021](../adr/0021-compliance-profiles.md)). The app has no
artifact store, so its evidence is the summary comment.

### Which pull requests the model reviews

The installation's key pays for every review, and anyone can open a pull request against a public
repository. So by default the model reviews only a branch of the same repository opened by an owner,
member or collaborator. A pull request from a fork, or by anyone else, gets bylaw's own checks, and its
summary says why and how to change it. Two settings open it up, in the organisation's defaults or a
repository's `.bylaw.toml`; the Action ignores them, since its workflow decides who runs it:

```toml
[app]
model_review = "all"                # every pull request, forks included
model_review_label = "bylaw: review"  # or: one pull request, once a maintainer adds this label
```

Adding a label reviews the pull request again, so the label works at once; only people with triage
access or more can add labels, which a fork's author cannot. In the app a pull request may also use at
most 500,000 model tokens across its runs unless `[budget] pr_tokens` says otherwise, roughly a hundred
small reviews or one or two of the largest.

### Limits a repository cannot raise

A default is only a default: a repository's `.bylaw.toml` can set `[app] model_review = "all"` or a
larger `[budget] pr_tokens`, and anyone who can merge to its default branch can do that. To hold every
repository to a limit, add a `[ceiling]` table to the organisation's defaults:

```toml
# acme/.github, .bylaw.toml
[ceiling]
model_review = "trusted"   # no repository can open the model review to every pull request
pr_tokens = 200000         # no pull request in any repository may use more model tokens
```

A repository's settings are cut to the ceiling. Under `model_review = "trusted"`, a repository's `"all"`
reads as `"trusted"`, and `model_review_label` comes from the organisation's file only: a repository's
label is ignored, because a label that an auto-labeller adds to every pull request would open the review
to every fork. Set the label in the defaults if maintainers should be able to unlock one pull request at
a time. A repository's `pr_tokens` is the smaller of its own value and the ceiling; one that sets none
gets the smaller of the app's default of 500,000 and the ceiling, so a high ceiling never raises the
default. Only the organisation's file sets a ceiling; a `[ceiling]` table in a repository's own
`.bylaw.toml` is ignored, so it can neither lift nor replace the organisation's.

## 5. Model keys per installation

Each organisation that installs the app is an installation with a number, shown at the end of the URL
of its settings page (`.../settings/installations/<id>`) and in every delivery's `installation.id`. Keys
are stored per installation, so each organisation pays for its own reviews and a server-wide key never
reviews anyone's code by accident.

With `BYLAW_SECRETS_DIR`, one file per secret:

```
/run/secrets/installations/
  12345678/
    ANTHROPIC_API_KEY
    JIRA_EMAIL
    JIRA_API_TOKEN
    JIRA_URL
```

Without it, from the environment: `BYLAW_INSTALLATION_12345678_ANTHROPIC_API_KEY=...`. The names are the
ones the Action and the CLI read: `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `BYLAW_API_KEY`, and the tracker
tokens `JIRA_EMAIL`, `JIRA_API_TOKEN`, `AZURE_DEVOPS_TOKEN` and `LINEAR_API_KEY` ([trackers.md](../trackers.md)),
plus `JIRA_URL` and `AZURE_DEVOPS_ORGANIZATION`, which only the app reads (below).
Nothing else is read. Keys are read on every review, so a rotated key takes effect without a restart,
and they are never written to the log.

Tracker tokens need one more secret each: where they may go. A token in the store serves every repository
of the installation, and anyone who can create a repository writes its `.bylaw.toml`, so the app does not
let that file choose the destination. Set `JIRA_URL` (such as `https://acme.atlassian.net`) next to
`JIRA_EMAIL` and `JIRA_API_TOKEN`, and `AZURE_DEVOPS_ORGANIZATION` next to `AZURE_DEVOPS_TOKEN`. A
repository whose `[jira] url` or `[azure_boards] organization` differs gets a note in its summary instead
of a request carrying the token, and without the pinning secret the tracker is not read at all. The
project and team allow lists still come from `.bylaw.toml`, so give the app a tracker account that can
read only what any repository in the organisation may quote. Linear's key always goes to Linear's API, so
it needs no pinning.

## 6. Health, logs and limits

- `GET /healthz` answers `{"status": "ok", "pending": 0, "running": 0}` without a signature, for your
  load balancer and the image's health check.
- The log has one line per delivery (queued, duplicate, superseded or busy) and the review's notes, with
  pull request text flattened to one line. A failed review is logged with its reason; configuration
  errors land here too, since the app has no failing check run to show them.
- Deliveries are answered within milliseconds and reviewed in the background. A pull request has at most
  one review waiting, and the review reads the pull request as it is when it starts, so a burst of
  pushes costs one review of the latest head. The head it read counts as reviewed: a delivery for a head
  already reviewed or waiting does nothing.
- The queue lives in memory. After a restart, a missed or lost review runs on the pull request's next
  push, or redeliver the event from the app's **Advanced** settings, which also retries a review that
  failed.
- On `docker stop` (SIGTERM) the server stops taking deliveries, starts no new review, and lets the
  reviews already running finish before it exits; reviews still waiting are dropped. Docker kills the
  container after 10 seconds by default, which can cut a review off between its inline comments and its
  summary, so give it longer than a review takes: `--stop-timeout 120` above, or
  `terminationGracePeriodSeconds: 120` in Kubernetes. A review that was cut off is redone by the next push
  or a redelivery: the inline comments it posted carry their fingerprints, so they are not posted again,
  and the summary is written then. The model tokens the cut-off run spent are not counted against
  `[budget] pr_tokens`. Checked on 18 October 2026: with a 60 second stop timeout the running review
  posted its summary and the container exited after 6 seconds; with 2 seconds it was killed before the
  summary.

## 7. Check it locally

`tools/app_smoke.py` runs the whole path without GitHub: it starts a fake GitHub on a local port, starts
the app against it with a throwaway key, waits for the health endpoint, posts one signed delivery and a
forged one, and waits for the review:

```
uv run python tools/app_smoke.py                    # the server as a local process
uv run python tools/app_smoke.py --image bylaw-app  # the built image, which must report healthy
```

It calls no model and sends nothing off the machine. What it cannot check, because it needs a real app
registration, is listed under "Live checks before v1.0" in [the backlog](../backlog/github-app.md).

## GitHub documentation this guide follows

- [Registering a GitHub App from a manifest](https://docs.github.com/en/apps/sharing-github-apps/registering-a-github-app-from-a-manifest)
- [Permissions required for GitHub Apps](https://docs.github.com/en/rest/authentication/permissions-required-for-github-apps)
- [Webhook events and payloads: pull_request](https://docs.github.com/en/webhooks/webhook-events-and-payloads#pull_request)
- [Validating webhook deliveries](https://docs.github.com/en/webhooks/using-webhooks/validating-webhook-deliveries)
- [Best practices for using webhooks](https://docs.github.com/en/webhooks/using-webhooks/best-practices-for-using-webhooks)
- [Generating a JSON Web Token for a GitHub App](https://docs.github.com/en/apps/creating-github-apps/authenticating-with-a-github-app/generating-a-json-web-token-jwt-for-a-github-app)
- [Create an installation access token for an app](https://docs.github.com/en/rest/apps/apps#create-an-installation-access-token-for-an-app)
