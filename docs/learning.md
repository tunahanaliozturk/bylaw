# Learning from maintainers

bylaw can remember what happened to its findings once a pull request closes, suggest a suppression when
maintainers keep waving the same kind of finding away, and publish a page that shows what its findings
led to. All of it is off until you turn it on, and none of it changes a review by itself: a suggestion is
a pull request you merge or close. The reasoning is in [ADR 0022](adr/0022-learning-and-reports.md).

## Turning it on

In `.bylaw.toml` on the default branch:

```toml
[learn]
enabled = true
threshold = 3        # pull requests in which maintainers dismissed the same kind of finding
suggest = ["rule"]   # what a suggestion may cover: rule, bug. Never security.
```

Then let the workflow run when a pull request closes. Give the review and the learning step a job each,
so only the step that writes to the repository gets write access to contents:

```yaml
name: bylaw
on:
  pull_request:
    types: [opened, synchronize, reopened, ready_for_review, closed]
permissions: {}
jobs:
  review:
    if: github.event.action != 'closed'
    runs-on: ubuntu-latest
    permissions:
      contents: read
      pull-requests: write
      issues: read
    steps:
      - uses: tunahanaliozturk/bylaw@v0
        with:
          api-key: ${{ secrets.ANTHROPIC_API_KEY }}
  learn:
    if: github.event.action == 'closed'
    runs-on: ubuntu-latest
    permissions:
      contents: write        # the bylaw-outcomes branch, and suggestion branches
      pull-requests: write   # suggestion pull requests
      issues: read
    steps:
      - uses: tunahanaliozturk/bylaw@v0
```

On every event but `closed` the Action reviews as before. On `closed` it runs `bylaw learn` instead, and
needs no model key. The review job reads text the pull request's author wrote and sends it to a model, so
it keeps `contents: read`: a review that went wrong can comment, never push.

A fork's `pull_request` run gets a read-only token, so its outcomes cannot be written and bylaw skips it
with a notice. To record fork pull requests too, run the closing step from `pull_request_target`, which
gets a write token in the base repository's context. That is safe for bylaw because it never checks out
or runs the pull request's code; keep it that way and never add a checkout of the head to that job.

## What is recorded

Each closed pull request becomes one file, `pulls/<number>.json`, on the `bylaw-outcomes` branch. The
branch shares no history with your code. A record holds, per finding, its fingerprint, category, the rule
it cites, its file, and what happened to it:

| Outcome | Meaning |
| --- | --- |
| `fixed` | The finding went away on a run in which the model read its file. |
| `muted` | A maintainer replied `bylaw: ignore`; `by` is their login. |
| `resolved` | Someone other than the author resolved its thread with the finding still there; `by` is their login. |
| `suppressed` | A `[[suppress]]` entry hid it. |
| `open` | None of these when the pull request closed. |

It also holds the pull request's author, whether it merged, when it closed, the head commit, and how many
criteria the last review found met, partial, missing and not assessed. It never holds code or messages.

Only bylaw's own summary is read, and only mutes from people with write access who did not write the
pull request count, as for every other run (ADR 0008). To keep collaborators from editing records by
hand, add a ruleset for the `bylaw-outcomes` branch that lets only GitHub Actions push to it.

## Suggestions

After recording, bylaw groups findings by category and the exact rule they cite. When maintainers
dismissed a group in at least `threshold` pull requests, more often than it was fixed, and no suppression
for that rule exists yet, bylaw opens a pull request that adds one to `.bylaw.toml`, with the pull
requests and maintainers that led to it in its body. Close it if you disagree, or if the better answer is
to make the rule clearer; bylaw never opens the same suggestion twice.

Opening one needs `pull-requests: write` and the repository setting **Allow GitHub Actions to create and
approve pull requests** (Settings, Actions, General), which is off by default; without it the closing run
fails with a message that says so, after the outcomes are recorded. At most three suggestions are opened
per closed pull request; earlier ones, merged or declined, do not take a place. A pull request opened with `GITHUB_TOKEN` does not start other workflows, so the
suggestion's own CI runs once someone pushes to it, or closes and reopens it.

Security findings are never suggested, and a suppression never hides one.

## Suppressions

A suppression is a decision you write down, whether bylaw suggested it or not:

```toml
[[suppress]]
rule = "ruff:S101"           # exactly as findings cite it: a linter id, or CONTRIBUTING.md:41
paths = ["tests/**"]         # optional: every file when left out
reason = "Tests use assert."
```

A finding that cites that rule in those paths, whatever its category except security, is not posted and
does not count for `fail-on`. Every
summary lists the suppressions in force, with their reason and how many findings each hid, and lists the
hidden findings in a collapsed section, so nothing disappears unseen. A suppression of a rule line, such
as `CONTRIBUTING.md:41`, stops matching when that file's lines move, and the findings come back; update
the line when you edit the rule.

## The report

`bylaw report --output DIR` reads the records and writes `index.html` with its charts into `DIR`:
findings per category and what happened to them, with the fix rate; criteria met, partly met, missing and
not assessed per month, for the last twelve months with records; and the rules maintainers dismissed in
the most pull requests. It needs no JavaScript and no web server. Each chart is a pair of PNG files, light
and dark, which the browser picks from your system theme, and each has a table with the same numbers. It
reads the newest 500 records.

The Action writes it when you set its `report` input, on a closed pull request or on a run that has no
pull request, such as a schedule:

- `report: artifact` uploads the page as the workflow artifact `bylaw-report`. Set it on the `learn` job
  above; it needs no other permission.
- `report: pages` publishes it to GitHub Pages. Set the repository's Pages source to GitHub Actions. The
  `github-pages` environment deploys only from the default branch, so publish from a workflow of its own:

```yaml
name: bylaw report
on:
  schedule:
    - cron: "0 6 * * 1"   # Mondays
  workflow_dispatch:
permissions:
  contents: read
  pages: write
  id-token: write
jobs:
  report:
    runs-on: ubuntu-latest
    environment:
      name: github-pages
    steps:
      - uses: tunahanaliozturk/bylaw@v0
        with:
          report: pages
```

On a public repository the Pages site is public, and it names your rules and how often they were waved
away. The records on the branch are visible to anyone who can read the repository either way.
