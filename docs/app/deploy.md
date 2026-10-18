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
docker run -d --name bylaw-app --restart unless-stopped -p 127.0.0.1:8000:8000 \
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

Settings, all from the environment:

| Variable | Default | Meaning |
| --- | --- | --- |
| `BYLAW_APP_CLIENT_ID` | required | The app's client ID (recommended by GitHub) or numeric app ID. |
| `BYLAW_APP_PRIVATE_KEY_FILE` | required | Path to the app's private key. `BYLAW_APP_PRIVATE_KEY` holds the PEM itself where files are not possible. |
| `BYLAW_WEBHOOK_SECRET_FILE` | required | Path to the webhook secret. `BYLAW_WEBHOOK_SECRET` holds it directly. |
| `BYLAW_SECRETS_DIR` | unset | Folder with one subfolder per installation for model keys and tracker tokens; unset reads them from the environment instead (section 5). |
| `BYLAW_PROVIDER` | `anthropic` | `anthropic` or `openai`, for every installation. |
| `BYLAW_MODEL`, `BYLAW_EFFORT` | provider default | As `--model` and `--effort` for `bylaw review`. |
| `BYLAW_APP_WORKERS` | `2` | Pull requests reviewed at once. |
| `BYLAW_APP_MAX_PENDING` | `100` | Pull requests that may wait; beyond that, deliveries get `503`. |
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
```

Without it, from the environment: `BYLAW_INSTALLATION_12345678_ANTHROPIC_API_KEY=...`. The names are the
ones the Action and the CLI read: `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `BYLAW_API_KEY`, and the tracker
tokens `JIRA_EMAIL`, `JIRA_API_TOKEN`, `AZURE_DEVOPS_TOKEN` and `LINEAR_API_KEY` ([trackers.md](../trackers.md)).
Nothing else is read. Keys are read on every review, so a rotated key takes effect without a restart,
and they are never written to the log.

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
