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

Then let the workflow run when a pull request closes, with write access to contents and pull requests:

```yaml
name: bylaw
on:
  pull_request:
    types: [opened, synchronize, reopened, ready_for_review, closed]
permissions:
  contents: write        # the bylaw-outcomes branch, and suggestion branches
  pull-requests: write
  issues: read
jobs:
  review:
    runs-on: ubuntu-latest
    steps:
      - uses: tunahanaliozturk/bylaw@v1
        with:
          api-key: ${{ secrets.ANTHROPIC_API_KEY }}
```

On every event but `closed` the Action reviews as before. On `closed` it runs `bylaw learn` instead.

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
per closed pull request. A pull request opened with `GITHUB_TOKEN` does not start other workflows, so the
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

A finding that cites that rule in those paths is not posted and does not count for `fail-on`. Every
summary lists the suppressions in force, with their reason and how many findings each hid, and lists the
hidden findings in a collapsed section, so nothing disappears unseen. A suppression of a rule line, such
as `CONTRIBUTING.md:41`, stops matching when that file's lines move, and the findings come back; update
the line when you edit the rule.
