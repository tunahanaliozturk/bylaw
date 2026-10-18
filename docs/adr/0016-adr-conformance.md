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

- **Where ADRs are.** A new setting, `adr_globs`, defaults to `docs/adr/**` (what most teams use),
  `doc/adr/**` (adr-tools' default) and `docs/decisions/**` (MADR's). bylaw lists every file under each
  glob's fixed directory on the base branch, subdirectories included, and keeps the Markdown files the
  glob matches, so `**/adr/**` or `services/*/docs/adr/*.md` work too. A `README.md`, an `index.md` and
  any file with "template" in its name are not ADRs. ADRs are read from the base branch, never from the
  head, like every other rule source. A pull request that edits or supersedes an ADR is reviewed against
  the base version, and the summary says so. An ADR the pull request adds is not a decision until it
  merges; the summary says that too, and the reviewer still reads it in the diff.
- **ADRs are not specs.** `docs/adr/**` leaves the default `spec_globs`, and a file that matches
  `adr_globs` is never a spec, even when an older configuration still lists it there or the pull request
  links it. So an ADR is counted once, as a decision, and a checklist inside it is never a criterion. A
  linked ADR that is not among the decisions gets a note, so the link does not vanish without a word.
- **Reading the Markdown.** Lines are numbered as GitHub numbers them: only a newline ends a line, so a
  form feed or a U+2028 inside a line does not shift every number after it. The same fix applies to the
  numbers of rule files and `.editorconfig` evidence. Headings and status lines inside code fences do not
  count, so a `# setup` comment in a shell example does not end the decision. A leading `---` front
  matter block is not a heading either. ATX and setext headings both count, with or without a number or
  bold (`## 3. Decision`, `## **Status**`).
- **Which ADRs count.** The status comes from a `Status:` line, a `| Status | ... |` table row or a front
  matter key above the first section (bylaw's own form, MADR 2 bullets, MADR 3 front matter, bold or
  not), or from a `## Status` section (Nygard, adr-tools), in any case. Links are removed first, because
  adr-tools writes lines such as `Supersedes [3. Keep the deprecated logger](...)` whose link text is not
  a status. The rest is read clause by clause, each by its first word after any bullet or date, and the
  last clause that names a status decides: accepted, approved, implemented, adopted or decided keep an
  ADR in force; superseded, deprecated, rejected, replaced, obsolete, withdrawn, declined or a clause that
  starts with "not" retire it; proposed, draft or pending leave it out. So "Accepted, superseded by 0012"
  is out, "Accepted. Supersedes 0003" and "Accepted. The old way is now obsolete" are in, and a history
  that ends in `2023-02-01 accepted` is in. The brief shows the clause's line, the effective status.
- **Proposed is out.** A proposal is still being argued about. The pull request may well be the
  experiment that settles it, and a finding that it "contradicts" a proposal would turn an open question
  into a rule nobody agreed to.
- **What bylaw cannot read is named.** An ADR without a status, with a status bylaw does not recognise or
  without a decision section is left out, and one note in the summary names each with the reason. A
  retired or proposed ADR is left out without a note, because that is what its status asks for.
- **What the reviewer sees.** A `decisions` block in the brief, after the rules: per ADR its path, title,
  status and decision section (`## Decision`, or MADR's `## Decision Outcome` with its subsections),
  numbered with the file's own line numbers. The title is the first level one heading, else the front
  matter's `title:`, so MADR's template comment is never a title. Context, consequences and the options
  considered stay out: they cost prompt space, and the options considered are exactly the ones the team
  turned down, which a reviewer must not cite as the rule.
- **Package ADRs bind their package.** As with the package rules of ADR 0013, an ADR applies to the
  directory above its `adr` or `decisions` directory and any `docs` or `doc` directory around that:
  `packages/api/docs/adr/0002-x.md` binds `packages/api/`, `docs/adr/0001-x.md` the whole repository. A
  package's ADRs are read only when the change touches that package, the brief says which files a package
  decision applies to, and validation drops a citation of a package decision on a file outside it.
- **How many, and at what cost.** Newest first, by the number in the file name. At most 40 files are
  read, all in one GraphQL query on GitHub (aliased `object(expression: "<sha>:<path>")` blobs, the paths
  passed as variables); a blob GraphQL truncates, or every file when the query fails, is read through the
  contents API. Each decision is cut at 2,000 characters on a line boundary (a single long line is cut
  inside it), and decisions stop at 12,000 characters in all, about 4,000 tokens. A note in the summary
  names an ADR whose decision was cut and the older files that were left out. No ADR means no cost: the
  block reads `(none)`.
- **Findings.** A change that goes against a decision is a `rule` finding citing `docs/adr/<file>.md:<line>`.
  Validation keeps the citation only when the line is inside the decision text the brief showed, and,
  for a package ADR, only on a file of that package; the status line, the context section or an ADR that
  was not shown are dropped as invented.
- **The rest of bylaw.** The incremental review key (ADR 0012) hashes the decisions with the rules and
  requirements, so an ADR that changes on the base branch forces a full review. The summary lists the
  ADRs used among its rule sources.

## Consequences

- A pull request that contradicts an accepted ADR gets a finding that names the ADR and the line. Two
  evaluation cases measure it: one change that breaks a decision, and a clean change in a project that
  also has a superseded and a proposed ADR the change would break if they counted.
- Cost: one more GitHub call per review for the ADR texts, whatever their number, plus one per ADR that
  GraphQL truncates. The listing comes from the base tree, one call per review, shared with the nested
  rules of ADR 0013.
- Cost: up to about 4,000 more input tokens per review. Repositories without ADRs pay nothing but the
  empty block.
- Cost: a reviewer can see a contradiction where there is none. The prompt asks for a finding only when
  the change goes against what was decided, not when it merely works in the same area, and the clean
  evaluation case counts false alarms.
- Cost: when there are more decisions than fit, older ones are left out even if they are the relevant
  ones. The note says which, and a team can narrow `adr_globs` or supersede stale ADRs.
- Cost: the status is read from its first words, so a status written as a sentence ("We accepted this in
  May") is not recognised. The summary names such an ADR, and the fix is a plain `Status: Accepted`.
- Not read: on a repository so large that GitHub truncates its tree, only the files directly in a glob's
  fixed directory are listed. The newest-first order needs a number in the file name; without one, files
  are taken in reverse name order. Package ADRs need a glob that reaches them, such as
  `packages/*/docs/adr/**`; the defaults look only at the root.
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
- **Every ADR binds the whole repository.** Lost once ADRs can be found in package directories: a
  worker package's decision to raise on errors would be cited against an API package that decided the
  opposite, the conflict ADR 0013 already solved for rules.
- **Look for a status word anywhere in the status text.** Tried first and lost: adr-tools' link lines and
  plain prose ("the deprecated logger", "rejected payments") retired accepted ADRs, and "Not accepted"
  counted as accepted.
- **One contents API call per ADR.** Tried first and lost on cost: 40 calls per review against the
  1,000 requests an hour a workflow's token gets per repository.
- **A separate model call that picks the relevant ADRs.** Lost because it doubles the paid calls for every
  review and the Claude Code and Codex path would need a second step.
