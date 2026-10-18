# 0016: Accepted ADRs are decisions a change is held to

Status: Accepted, 2026-10-18. Builds on 0004 and 0013; takes `docs/adr/**` out of the spec globs of 0003.

## Context

Teams write their decisions down as ADRs and then forget them. A pull request that stores money as a
float, in a repository whose ADR says integer cents, passes review because nobody remembered the ADR.
bylaw already reads the repository's written rules, and an accepted ADR is a written rule too.

Until now `docs/adr/**` was one of the spec globs. An ADR reached the reviewer only when the pull request
changed it or linked it, it was read from the head, and it came in as a requirement: a checklist inside an
ADR became acceptance criteria for the pull request to tick. That is the wrong shape. A decision is not
work to finish; it is a constraint on every later change, including the ones that never mention it.

The limits are the same as for the other rule sources (ADR 0004, 0013): the brief must stay small, each
file read from GitHub is an API call, and the pull request is untrusted, so it must not be able to change
what it is held to.

## Decision

- **Where ADRs are.** A new setting, `adr_globs`, defaults to `docs/adr/**` and `docs/decisions/**`, the
  directories adr-tools, most teams and MADR use. bylaw lists the Markdown files directly in each glob's
  directory on the base branch and reads them from there, never from the head, like every other rule
  source. A pull request that edits or supersedes an ADR is reviewed against the base version, and the
  summary says so. An ADR the pull request adds is not a decision until it merges; the reviewer still
  reads it in the diff.
- **ADRs are not specs.** `docs/adr/**` leaves the default `spec_globs`, and a file that matches
  `adr_globs` is never a spec, even when an older configuration still lists it there or the pull request
  links it. So an ADR is counted once, as a decision, and a checklist inside it is never a criterion.
- **Which ADRs count.** The status comes from a `Status:` line or front matter key above the first
  section (bylaw's own form, MADR 2 bullets, MADR 3 front matter, bold or not), or from a `## Status`
  section (Nygard, adr-tools), in any case. An ADR is in force when its status says accepted or approved
  and does not also say superseded, deprecated, rejected, replaced, obsolete or withdrawn: "Accepted,
  superseded by 0012" is out, "Accepted. Supersedes 0003" is in. Proposed and draft ADRs are out, and so
  is an ADR with no status or no decision section.
- **Proposed is out.** A proposal is still being argued about. The pull request may well be the
  experiment that settles it, and a finding that it "contradicts" a proposal would turn an open question
  into a rule nobody agreed to.
- **What the reviewer sees.** A `decisions` block in the brief, after the rules: per ADR its path, title,
  status and decision section (`## Decision`, or MADR's `## Decision Outcome` with its subsections),
  numbered with the file's own line numbers. Context, consequences and the options considered stay out:
  they cost prompt space, and the options considered are exactly the ones the team turned down, which a
  reviewer must not cite as the rule.
- **How many.** Newest first, by the number in the file name. At most 40 files are read, each decision
  is cut at 2,000 characters on a line boundary (a single long line is cut inside it), and decisions stop
  at 12,000 characters in all, about 4,000 tokens. A note in the summary names an ADR whose decision was
  cut and the older files that were left out. No ADR means no cost: the block reads `(none)`.
- **Findings.** A change that goes against a decision is a `rule` finding citing `docs/adr/<file>.md:<line>`.
  Validation keeps the citation only when the line is inside the decision text the brief showed; the
  status line, the context section or an ADR that was not shown are dropped as invented. Decisions hold
  for the whole repository, so the package rule of ADR 0013 does not apply to them.
- **The rest of bylaw.** The incremental review key (ADR 0012) hashes the decisions with the rules and
  requirements, so an ADR that changes on the base branch forces a full review. The summary lists the
  ADRs used among its rule sources.

## Consequences

- A pull request that contradicts an accepted ADR gets a finding that names the ADR and the line. Two
  evaluation cases measure it: one change that breaks a decision, and a clean change in a project that
  also has a superseded and a proposed ADR the change would break if they counted.
- Cost: up to 40 more GitHub calls per review in a repository with many ADRs, one per file. The listing
  comes from the base tree, one call per review, shared with the nested rules of ADR 0013.
- Cost: up to about 4,000 more input tokens per review. Repositories without ADRs pay nothing but the
  empty block.
- Cost: a reviewer can see a contradiction where there is none. The prompt asks for a finding only when
  the change goes against what was decided, not when it merely works in the same area, and the clean
  evaluation case counts false alarms.
- Cost: when there are more decisions than fit, older ones are left out even if they are the relevant
  ones. The note says which, and a team can narrow `adr_globs` or supersede stale ADRs.
- Not read: ADRs in subdirectories of a glob's directory, ADRs without a status or a decision section,
  and statuses bylaw does not recognise. The newest-first order needs a number in the file name; without
  one, files are taken in reverse name order.
- A configuration that lists `docs/adr/**` under `spec_globs` loses nothing it should keep: a changed ADR
  is no longer a requirement, and an accepted one is now a decision.

## Alternatives

- **Keep ADRs as specs.** Lost because a decision is a constraint, not a checklist, and an ADR only
  counted when the pull request touched it, read from the head the pull request controls.
- **Read ADRs from the head.** Lost for the reason ADR 0004 gives: a pull request could supersede the
  decision it breaks in the same change and pass. It would win only if decisions were advice.
- **Pick ADRs by keyword overlap with the changed paths.** Lost because it is hard to explain why an ADR
  was not shown, and the ADR that matters often shares no word with the file names (a money decision does
  not mention `cart.py`). It would win in a repository with hundreds of accepted ADRs, where newest first
  leaves out too many.
- **The whole ADR.** Lost on size, and because the options considered would invite citations of what the
  team rejected.
- **Proposed ADRs too, marked as proposals.** Lost because a proposal is not binding. It would win for a
  team that never moves its ADRs past "proposed"; a setting could add that later.
- **A separate model call that picks the relevant ADRs.** Lost because it doubles the paid calls for every
  review and the Claude Code and Codex path would need a second step.
