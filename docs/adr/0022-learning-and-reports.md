# 0022: Learning from maintainers, and a report, from an outcome branch in the repository

Status: Accepted, 2026-10-19. Builds on 0004, 0005, 0008, 0012 and 0021.

## Context

Maintainers already tell bylaw when a finding is not worth a comment: they reply `bylaw: ignore`, or
they resolve the thread and leave the code as it is. When the same kind of finding gets that treatment
on pull request after pull request, the rule behind it is either too broad for part of the code or
written unclearly, and bylaw should say so. A team also wants to see, across pull requests, what bylaw
found and what happened to it: how much was fixed, how much was waved away, and how the linked criteria
fared over time.

Both need memory across pull requests, and bylaw has none. ADR 0005 keeps state in each pull request's
summary comment, which disappears with the pull request, and the Action has no server or database. The
questions are where that memory lives, who may write to it, what counts as "the same kind of finding"
when a fingerprint includes the code, how a suggestion reaches the repository without bylaw changing
its own rules, and whether a security finding can ever be suggested away.

## Decision

**Per pull request, the summary state keeps each finding's outcome (LRN-1).** Next to the review memory,
the state holds, per fingerprint, the finding's status and what it is about: its category, the evidence
it cites (the rule, as a suppression would name it) and its file. The statuses are `open`; `fixed`, when
the finding is gone on a run in which the model read its file (a finding on a file the model skipped
stays open, as in ADR 0012); `muted` with the login of the maintainer whose `bylaw: ignore` counted;
`resolved` with the login of whoever resolved the thread while the finding was still there; and
`suppressed`. A mute or resolve stays once made, even when the code changes later, because the
maintainer's call was about that finding. The pull request author's resolve accepts nothing (ADR 0008),
so such a finding stays `open`. The state also keeps how many criteria the last run found met, partial,
missing and not assessed. Like the review memory, outcomes are carried from one run to the next only
from a summary a bot wrote: a member with read access could otherwise post a summary claiming that
maintainers muted everything. Outcomes get at most 12,000 characters of the comment, measured after
escaping, with mutes and resolves kept first because they are what learning counts.

**Across pull requests, outcomes live on a branch of the same repository (LRN-2).** When a pull request
closes, `bylaw learn --pr N` reads its summary (a bot's only), applies any mute or resolve made since the
last run with the same trust rules, and writes one file, `pulls/<number>.json`, to the `bylaw-outcomes`
branch. The branch is an orphan: it shares no history with the code, so it never shows in a diff, a
merge or a release. The Action runs this step instead of the review when the event is `closed`.

- *One file per pull request, not an append-only log.* Two pull requests that close at the same time
  write different paths, so their changes never conflict, and closing a pull request again (reopened,
  then closed) replaces its record instead of counting it twice.
- *Concurrency.* Each write is a commit made through the Git Data API (tree, commit, then the ref moved
  with `force: false`). When another writer moved the branch in between, GitHub refuses the update with a
  422 and bylaw makes its commit again on top of theirs, up to five times. Nothing is lost and nothing is
  overwritten.
- *Size.* A record holds hashes, short strings and logins, never code or messages: a few hundred bytes to
  about 15 KB. Reports and suggestions read the newest 500 records, in batches of 100 files per GraphQL
  query, so reading cost does not grow with the repository's age.
- *Permissions.* Writing needs `contents: write` on the job, which the default workflow does not grant.
  Without it the write fails with a message that names the permission. Learning is off by default, so
  nothing changes for a repository that does not turn it on.
- *Forks.* A fork's `pull_request` run has a read-only token and no secrets; bylaw skips it with a
  notice. To record fork pull requests, the closing workflow runs on `pull_request_target`, which is safe
  here for the reason ADR 0006 gives: bylaw never checks out or runs the pull request's code.

**Trust.** A planted outcome could at worst make bylaw open a suggestion pull request, because nothing is
ever applied without a maintainer merging it. Even so:

- Outcomes come from a bot-written summary only, and mutes only from trusted authors who are not the
  pull request's author (ADR 0008), checked when the run is planned and again when the pull request
  closes.
- When records are counted, a dismissal counts only with a login that differs from the record's author.
- The branch can be written only by accounts with write access to the repository, who could edit
  `.bylaw.toml` anyway. docs/learning.md suggests a ruleset that lets only GitHub Actions push to
  `bylaw-outcomes`, which also keeps collaborators from editing records by hand.

**What "the same kind of finding" means.** A fingerprint includes the code snippet, so it never repeats
across pull requests. Findings are grouped by their category and the evidence they cite, exactly: the
same rule line (`CONTRIBUTING.md:41`), the same linter id (`ruff:S101`) or the same `.editorconfig`
property line. A finding that cites nothing, which is most bug and every security finding the model
writes in its own words, is never grouped, because two model messages that say the same thing in other
words are not a reliable key. When a rule file is edited and its lines move, its counts start again;
that is the safe direction, since a count that is too low only means a suggestion comes later.

**Suggestions are pull requests, never silent changes (LRN-3).** After recording, bylaw counts, for each
group, the distinct pull requests in which maintainers muted or resolved such a finding and those in
which it was fixed. When the dismissals reach `[learn] threshold` (3 by default, at least 2) and
outnumber the fixes, and no suppression for that rule exists yet, bylaw opens a pull request against
the reviewed pull request's base branch that appends a `[[suppress]]` entry to `.bylaw.toml`. Its paths
are the deepest directory the dismissed findings share (every file when they share none), its reason
says how many pull requests dismissed it, and the body lists them and who dismissed each, with logins
in code spans so nobody is notified. The branch is `bylaw/suppress-<hash of the group>`. If any pull
request, open or closed, was ever opened from that branch, bylaw does not open another: closing a
suggestion unmerged is the maintainers' answer, and bylaw respects it. At most three suggestions open per
run. The body says that a rule clarification may be the better fix, in which case the maintainer closes
the suggestion and edits the rule.

**Security findings are never suggested away.** `suggest` accepts `rule` and `bug` only, so a
configuration that asks for `security` is an error, and a suppression never hides a security finding
even when it names the rule the finding cites. Waving away a security finding is a decision about a
specific change; a pattern of such decisions is a reason to look harder, not to stop looking.

**`[learn]` is read from the base branch (LRN-4)**, like every setting (ADR 0004): `enabled` (false),
`threshold` (3) and `suggest` (`["rule"]`).

**Suppressions are part of the configuration, and always visible (LRN-5).** A `[[suppress]]` entry names
a rule exactly as findings cite it, the paths it covers (every file when left out) and a required
`reason`. Validation of `.bylaw.toml` refuses an entry without a rule or a reason, with an empty path
list, or with any other key. A suppression hides only a finding that cites its rule in one of its paths,
and never a security finding. Hidden findings are not posted and do not count for `fail-on`, but the
summary lists every suppression in force with its reason and how many findings it hid on this run, says
in one line what a suppression can and cannot hide, and lists the hidden findings in a collapsed
section. The compliance evidence (ADR 0021) marks them `suppressed`. The suppressions travel in the
review context, so a local review and `bylaw post --dry-run` honour them too, and `bylaw post` and the
Action use the base branch's own list, never the context file's.

**A report from the same records (RPT-1 to RPT-3).** `bylaw report --output DIR` reads the records and
writes a static page: findings by category and what happened to them (fixed, muted, resolved,
suppressed, still open at close), the fix rate, the rules dismissed most often and the criteria met per
month. It needs no JavaScript. The charts are PNG files in light and dark versions, chosen by
`prefers-color-scheme`, drawn by bylaw itself with a small bitmap font and written with `zlib`: no new
dependency, no headless browser in CI and nothing to install on a runner. Each chart has a data table
next to it with the same numbers, which is what a screen reader reads. The Action's `report` input
publishes the page as a workflow artifact (`artifact`) or to GitHub Pages (`pages`) when a pull request
closes or the workflow runs on a schedule or by hand.

## Consequences

- A team that turns learning on gets a suggestion pull request once a rule has been waved away often
  enough, with the evidence in its body, and a page that shows what bylaw's findings led to.
- Cost: the closing run needs `contents: write` and, for suggestions, `pull-requests: write`. A pull
  request opened with `GITHUB_TOKEN` does not start other workflows, so the suggestion's CI runs only
  after someone pushes to it or closes and reopens it; docs/learning.md says so.
- Cost: a repository gets one more branch. Its files are small, but a busy repository adds one commit
  per closed pull request.
- Cost: a mute made after the pull request closed is not seen; there is no event for it to run on.
- Cost: outcomes kept with a personal token are never carried forward, because its summary is not a
  bot's, so `fixed` is never recorded with one. Mutes still are, when the pull request closes.
- Not covered yet: the GitHub App, whose installation token is read-only on contents (ADR 0017), and
  GitLab. Both would need their own store and permissions decision.
- The report is only as good as the records. A repository that turned learning on last week has a
  week of data, and the page says how many pull requests it covers.

## Alternatives

- **Actions artifacts as the store.** Lost because artifacts expire with the retention setting (90 days
  by default), belong to one workflow run and need a listing across runs to read back. A store that
  forgets in three months cannot learn a pattern.
- **Actions cache.** Lost for the reason ADR 0005 gives: caches are evicted and scoped per branch.
- **An append-only JSON lines file on the branch.** Lost because two pull requests closing at the same
  time edit the same file, so every write races, and a pull request closed twice is counted twice.
- **Issues or a pinned discussion as the store.** Lost because anyone who can comment could add to it,
  and editing a long comment body races in the same way.
- **The GitHub App's own storage.** Lost for now: the app keeps no database by design (ADR 0017), and
  the Action is where most repositories run bylaw.
- **Group by message text, or by an embedding of it.** Lost because model messages vary between runs;
  a grouping that is sometimes wrong would suggest suppressing a different problem than the one
  maintainers waved away.
- **Apply a suppression automatically past the threshold.** Lost because the roadmap's promise is that
  bylaw never silently changes what it reviews, and because a pull request is where a team discusses
  whether the rule or the suppression should change.
- **Allow security suggestions with a higher threshold.** Lost because the cost of one wrong suppression
  of a security rule is far larger than the noise it saves.
- **Charts as inline SVG.** Simpler, and crisp at any size, but the roadmap asks for PNG charts that can
  also be dropped into a README or a chat, where SVG with theme-dependent colours does not travel well.
  A headless browser, as `tools/flow_diagram.py` uses for the README diagram, is fine on a developer's
  machine but too heavy for every Action run.
