# Security policy

## Supported versions

| Version | Security fixes |
| --- | --- |
| Latest 1.x minor | Yes |
| Older 1.x minors | No: update to the latest minor, which is compatible ([docs/compatibility.md](docs/compatibility.md)) |
| 0.x | No, from the day 1.0 is released |

Once 2.0 is released, the last 1.x minor keeps getting security fixes for six months.

A fix ships as a new patch release of the supported minor, and the `v1` tag of the Action moves to it.

## Reporting a vulnerability

Report it privately through GitHub: the **Security** tab of this repository, then **Report a
vulnerability** (GitHub's private vulnerability reporting). Please do not open a public issue, discussion
or pull request for it.

Include what you found, how to reproduce it, the version or commit, and what an attacker gains.

- You get a first answer within 7 days.
- A confirmed issue gets a fix, or a plan with a date, within 30 days.
- We disclose in coordination with you, and at the latest 90 days after your report, whether or not a
  fix is out by then. If a fix needs longer, we agree on a date with you first.

You are credited in the advisory unless you ask not to be.

## Using bylaw safely

- **Pin the Action by commit.** `@v1` is the convenient choice and follows the newest 1.x release. A tag
  can be moved, so in a workflow that holds a model key, pin the full commit SHA of a release with the
  tag in a comment, `uses: tunahanaliozturk/bylaw@<commit sha> # v1.0.0`, and let Dependabot or Renovate
  keep it current. The commit of each release is on its release page.
- **Pin the CLI and its dependencies.** `uvx bylaw@1.0.0` fixes bylaw but resolves its dependencies on
  every run. Set `UV_EXCLUDE_NEWER` to the release's date, as the GitLab recipe does, or install from a
  requirements file with hashes ([docs/hosts.md](docs/hosts.md#gitlab-ci)).
- **Give each job the least it needs.** The review needs `contents: read`, `pull-requests: write` and
  `issues: read`. Only the separate job that records outcomes when a pull request closes needs
  `contents: write` ([docs/learning.md](docs/learning.md)).
- **Fork pull requests** go through [the `pull_request_target` recipe](docs/recipes/pull-request-target.yml)
  as written: label gated, no checkout of the head, runs queued rather than cancelled, and a
  `[budget] pr_tokens` cap.
- **Maintainers of this repository** protect the `v*` tags with a tag ruleset that blocks updates and
  deletions, so a published tag cannot be moved to other code.

## Scope

bylaw runs on untrusted input (pull request diffs, titles and bodies, commit messages, issues, work
items and specs) with a write token and often a model key. These are in scope:

- **The GitHub Action and the CLI**: text in a pull request, issue, work item or spec that makes bylaw
  post something it should not, approve, hide or mute a finding, or leak data, including prompt injection
  that gets past validation.
- **Secrets**: a model key, a GitHub or GitLab token, a tracker token, the GitHub App's private key or
  webhook secret reaching a log, a comment, an error message, an artifact or another host.
- **Configuration**: a way for a pull request to change the rules, `.bylaw.toml` or the organisation's
  defaults used to review it, or for a repository to lift a limit the organisation set.
- **Code execution** through the Action, including the `pull_request_target` recipe used as documented,
  and through git when bylaw reviews a local repository.
- **The GitHub App**: webhook signature checks, a delivery that makes the server act for another
  installation or repository, a token wider than the repository it reviews, an installation's key paying
  for another's reviews, and floods that starve other installations.
- **The MCP server**: reading a repository outside the allowed roots, posting without `--allow-post`, or
  sending tracker tokens to a host the server's environment did not pin.
- **GitLab**: a quick action run through bylaw's notes, a note author bylaw should not trust, or a
  confidential issue's text in a summary.
- **Trackers** (Jira, Azure Boards, Linear): a work item outside the allow list being read or quoted, a
  token sent to another site, or a note that tells a pull request author which keys exist.
- **Learning and the report**: forging an outcome or a suggestion pull request, a dismissal by a pull
  request's own author counting, or markup in a record reaching the HTML report unescaped.

Out of scope:

- A model missing a finding or making a wrong one. That is a quality issue; please open a normal issue.
- Workflows that ignore the warnings in [docs/recipes/](docs/recipes/), such as checking out the head of
  a fork pull request under `pull_request_target`.
- Someone who already has write access to the repository, the organisation's `.github` repository, the
  workflow files or the CI/CD variables. They can change what bylaw runs or read its secrets without
  bylaw.
- A bot account the repository chose to install writing bylaw's markers (ADR 0008 trusts bots by account
  type).
- The model provider, GitHub, GitLab or a tracker misbehaving, and denial of service against the
  operator's own GitHub App server by an installation the operator accepted.
- Pointing `bylaw mcp` at a repository you do not trust: git applies a repository's own configuration,
  and bylaw switches off only the parts that start programs ([docs/mcp.md](docs/mcp.md)).

## How bylaw protects itself

- **Rules and settings come from the base.** Rules, ADRs and `.bylaw.toml` are read from the base branch,
  the organisation's defaults from its `.github` repository's default branch, so a pull request cannot
  change how it is reviewed ([ADR 0004](docs/adr/0004-rules-from-base-branch.md)). The organisation's
  `[ceiling]` caps `[app] model_review` and `[budget] pr_tokens` for every repository
  ([ADR 0017](docs/adr/0017-github-app.md)).
- **Untrusted text stays data.** Repository text reaches the model inside randomly tagged data blocks,
  and the brief says to treat it as data.
- **Every finding is validated** before it is posted: it must sit on lines the change adds, cite a rule
  line, criterion or linter rule that exists, and stay within size limits, so one oversized finding
  cannot stop the rest of the review.
- **Only bylaw and maintainers carry state.** A comment counts as bylaw's own, or as a maintainer's
  `bylaw: ignore`, only when its author is a bot or has write access, and never when it is the pull
  request's own author. The summary is a bot's comment or, with a personal token, the token owner's; a
  person's comment is never edited. Review memory and outcomes are read only from a bot's summary, and
  every finding still open is listed in the summary
  ([ADR 0008](docs/adr/0008-trusted-authors-carry-state.md)).
- **Rendering is inert.** Every string bylaw did not write is escaped; mentions get a zero-width space,
  issue references sit in code spans, and bylaw's markers and hidden state are written last, so text in
  a finding cannot stand in for them. On GitLab every line that could run a quick action is made inert.
- **Secrets stay where they belong.** The Action passes inputs through environment variables, never into
  a script. Tracker tokens come from the environment only; requests to trackers follow no redirects and
  go only to HTTPS sites on the allow list, pinned by the operator in the GitHub App and in `bylaw mcp`.
  Errors are sanitised and never include keys, and an OpenAI-compatible request asks the provider not to
  store it.
- **The Action runs from its own source.** It installs bylaw from its own commit with `uv sync --locked
  --no-dev`, never checks out the pull request, and uses third-party actions pinned by commit
  ([ADR 0009](docs/adr/0009-action-runs-from-its-own-source.md)).
- **The GitHub App** checks the webhook's HMAC on the raw body before parsing it, caps body size and
  queues, binds to 127.0.0.1 unless told otherwise, runs as a non-root user in an image pinned by digest,
  scopes each installation token to the one repository and the permissions a review needs, and spends an
  installation's key only on pull requests its settings allow, within a default token budget.
- **The MCP server** reads only repositories whose work tree and git directories are inside its roots,
  lists `post` only with `--allow-post` and checks the head again before posting, and turns off git's
  textconv, external diff, fsmonitor and signature programs for its own commands.
- **Releases** are built with a build backend pinned by hash, published to PyPI
  through trusted publishing behind an environment that needs a maintainer's approval, and CI runs with
  read-only tokens, CodeQL, Dependabot and a licence audit.

The last whole-tool review is [docs/security-review-1.0.md](docs/security-review-1.0.md).
