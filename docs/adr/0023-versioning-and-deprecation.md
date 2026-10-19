# 0023: Versioned configuration and result files, and a deprecation policy

Status: Accepted, 2026-10-19. Builds on 0005, 0012 and 0021.

## Context

From 1.0 bylaw promises that an upgrade does not break what people already have. That is several kinds
of file, each kept for a different time and read by different software:

- `.bylaw.toml`, in every repository that uses bylaw, and in an organisation's `.github` repository for
  the GitHub App. It outlives any one bylaw version by years.
- The context file `bylaw context` writes and the result file a host model writes. `bylaw validate`,
  `bylaw post`, `bylaw prompt`, `bylaw review --context` and the MCP tools read them. A host may write a
  result with one bylaw and post it with another, for example after `uvx bylaw@latest` moves.
- The state in the summary comment: resolved thread ids and the review memory (ADR 0005, ADR 0012). It
  sits on every open pull request when a new bylaw starts reading it.
- The evidence file (ADR 0021), which an auditor may keep for years. It already has `schema_version`.
- The evaluation run files under `eval/results`, which `bylaw eval score` reads again.

Until now none of these said which format it was in, except the evidence. If a later bylaw changed what
a field means, it would read an old file as if it meant the new thing, and nothing would say so.

## Decision

- **`.bylaw.toml` has an optional `version`.** Absent means 1, so every file written for 0.x keeps its
  meaning and nobody has to edit anything for 1.0. The bylaw that reads a version it does not know stops
  with an error that names the file, the version it says and the versions this bylaw reads. A value that
  is not a number is refused without being repeated, like every other value in that file, because it may
  be a token pasted in the wrong place. In the GitHub App the organisation's defaults file is checked on
  its own, so the error names the file that is wrong.
- **The context and the result carry `schema_version`.** Absent means 1, which is what every 0.x file is.
  bylaw writes it into every context and result it writes: `bylaw context`, the output of `bylaw
  validate` and `bylaw review`, and the evaluation runs. An unknown version fails with the same kind of
  message. A host that writes a result does not need to add it.
- **The model is never asked for a version.** It fills `OutReview`, the strict schema in `engine.py`, in
  which every field is required. A constant field would cost output tokens on every review and give the
  model one more thing to get wrong, and bylaw already knows the version it is. The version is added
  when bylaw turns the answer into a `ReviewResult`.
- **The evidence keeps its own `schema_version`** (ADR 0021). Each file has its own number, because they
  change at different times: a new evidence field must not make every result file look new.
- **The summary state and the review memory are not versioned.** bylaw is their only reader and writer,
  and ADR 0005 already reads a state it cannot parse as empty, which is noisy but never loses a finding.
  The memory forces a full review whenever the bylaw version changes (ADR 0012), so a version inside it
  would add nothing. What must survive an upgrade is the fingerprint in each inline comment, which pairs
  a thread with its finding, and the thread ids bylaw resolved; the compatibility tests read a summary
  and comments that 0.2.0 wrote to keep both honest.
- **When a version goes up.** A field that goes away, is renamed, or changes meaning raises the file's
  version. A new optional field with a default does not, because older files simply lack it.
- **Which way the promise runs.** A bylaw reads every version it lists, and files written by any 0.x
  release. An older bylaw is not promised to read a newer file: the models forbid unknown fields, so a
  typo in a host's result or in `.bylaw.toml` fails instead of being ignored, and a file with a field
  added later fails on that field. The version covers the case that would otherwise pass silently, the
  same names meaning something else.
- **Deprecation before removal.** A configuration key, CLI flag, Action input or output, JSON field or
  MCP tool is removed only in a major release, after at least one minor release in which it still works
  and warns. A deprecated `.bylaw.toml` key gives a note in the summary comment, where the maintainers
  see it, and a line on standard error; a deprecated flag gives a line on standard error, which in the
  Action is the workflow log. docs/compatibility.md lists what counts as a public interface.

## Consequences

- An upgrade that changes a format fails loudly on the files it cannot read, instead of misreading them.
- Every context and result file grows by one line.
- tests/fixtures/0.x holds files that 0.1.1, 0.2.0 and 0.6.0 really wrote, and tests read them on every
  run. A change that breaks one of them fails the build, and the fixture is never edited to make it pass.
- Cost: an older bylaw still fails on a newer file with an unknown field, with pydantic's message rather
  than one about versions. Mixing versions in one flow is rare, because the skill pins the CLI to its
  own version (`uvx bylaw@<version>`).

## Alternatives

- **One version for every file.** Lost because the files change at different rates: a new evidence
  field would raise the number on result files that did not change.
- **Ignore unknown fields so older readers accept newer files.** Lost because a misspelt key in
  `.bylaw.toml` or a misnamed field in a host's result would then be dropped without a word, and an
  unknown configuration key may be a token that has to be rotated.
- **A version in the summary state.** Lost for the reasons above: an unreadable state already falls back
  safely, and the memory already resets on a new bylaw version.
- **Require `version` in `.bylaw.toml` from 1.0.** Lost because it would break every configuration
  written for 0.x on the release that promises not to break them.
