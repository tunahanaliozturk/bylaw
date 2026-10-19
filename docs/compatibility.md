# Compatibility and deprecation

From 1.0, bylaw follows [Semantic Versioning](https://semver.org/). This page says what that covers, so
you know what an upgrade can change under you and what it cannot. The reasoning is in
[ADR 0023](adr/0023-versioning-and-deprecation.md).

## What is a public interface

These are the parts people build on. A patch or minor release does not remove them or change what they
mean.

- **CLI commands and flags:** `bylaw context`, `validate`, `post`, `schema`, `prompt`, `review`, `eval`,
  `mcp`, `learn` and `report`, each with its flags, and the exit codes: 0 for success, 1 when `--fail-on` finds a finding
  at or above its severity (or an `eval run` case failed), 2 for an error.
- **`.bylaw.toml`:** every key and table in the README's configuration section and in
  [trackers.md](trackers.md), with its default and its meaning, plus `version`.
- **Action inputs:** `api-key`, `provider`, `model`, `base-url`, `base-url-api-key`, `effort`, `fail-on`,
  `github-token`, `jira-email`, `jira-api-token`, `azure-devops-token`, `linear-api-key` and `report`. The
  Action has no outputs today; the artifact names `bylaw-evidence-pr-<number>` and `bylaw-report` count
  as outputs.
- **JSON files:** the context `bylaw context` writes, the result a reviewer writes (the shape `bylaw
  schema` prints), the `{"result", "dropped"}` object `bylaw validate` and `bylaw review` print, and
  the evidence file, whose fields [compliance.md](compliance.md) lists, and the outcome records on the
  `bylaw-outcomes` branch (`pulls/<number>.json`, with `schema_version`), described in
  [learning.md](learning.md).
- **MCP tools:** `context`, `brief`, `schema`, `validate`, `preview` and, with `--allow-post`, `post`,
  with their arguments ([mcp.md](mcp.md)).
- **GitHub App settings:** the `[app]` table, the organisation defaults file, and the environment
  variables in [app/deploy.md](app/deploy.md), such as `BYLAW_APP_MAX_PENDING_PER_INSTALLATION` and the
  `BYLAW_INSTALLATION_<id>_<NAME>` secrets.
- **Environment variables** for keys, tokens and sites, such as `BYLAW_API_KEY`, `JIRA_URL` and
  `AZURE_DEVOPS_ORGANIZATION`.
- **What a pull request already carries:** a summary comment and inline threads written by an earlier
  bylaw keep working after an upgrade. Muted and resolved threads stay muted and resolved, and fixed
  findings are not posted again.

These are not public, and may change in any release, with a line in the changelog when it matters:

- The Python modules. bylaw is a command line tool, an Action and an app, not a library.
- The brief the model reads, the system prompt and the wording of comments, notes and the summary.
- Which findings a model reports. That is a judgement, and it varies from run to run.
- The defaults that follow providers, such as the default model, which moves when a provider retires
  one. The changelog says when.
- The evaluation report's layout.

## What each release may change

- **Patch (1.2.x):** fixes. A fix may stop bylaw from doing something it did wrongly, such as posting a
  comment on a line the change does not add.
- **Minor (1.x):** new commands, flags, keys, fields and tools, and deprecations. A new field in a JSON
  file is optional, so older files stay valid.
- **Major (2.0):** removals, and changes to what something means. Only interfaces deprecated in an
  earlier minor release are removed.

## Deprecation

Before anything public is removed, it is deprecated for at least one minor release: it keeps working,
and bylaw says it is going and what to use instead. The changelog has a "Deprecated" line in that
release and a "Removed" line in the major release that removes it.

How bylaw tells you:

- **A `.bylaw.toml` key:** a note in the summary comment, where the maintainers who own the file see it,
  and the same line on standard error, which in the Action is the workflow log. The note names the key
  and what replaces it.
- **A CLI flag or an Action input:** a warning on standard error each time it is used. An Action input
  maps to a CLI flag, so the warning lands in the workflow log.
- **A JSON field:** the field keeps being written and read until the major release; the changelog and
  this page say which one replaces it.
- **An MCP tool or argument:** its description starts with "Deprecated", and the server keeps serving it
  until the major release.

## Versioned files

| File | Field | Read as when absent |
| --- | --- | --- |
| `.bylaw.toml` | `version` | 1 |
| context file | `schema_version` | 1 |
| result file | `schema_version` | 1 |
| evidence file | `schema_version` | always written |

A file that names a version bylaw does not read fails with a message that names the version it found and
the ones bylaw reads. A field that goes away or changes meaning raises its file's version, in a major
release; a new optional field does not. You never need to write `schema_version` yourself, and a model
never sees it. The summary comment's hidden state is not versioned: bylaw reads a state it cannot parse
as empty, which costs a full review and never loses a finding.

A newer bylaw reads files from older ones. An older bylaw is not promised to read files from a newer
one, so run `bylaw context` and `bylaw post` from the same version, as the skill does.

## For contributors

- **Deprecating a key:** add it to `DEPRECATED_KEYS` in `src/bylaw/config.py` with what to use
  instead, written as a sentence. A key inside a table is written with a dot, `app.model_review`. The
  key stays a field of `Config`, so it keeps working.
- **Deprecating a flag:** pass `deprecated=True` to its `add_argument`, which makes argparse warn on
  standard error, and say in its help what replaces it.
- **Changing a file's meaning:** raise its version and keep reading the old one, or wait for a major
  release.
- **Every release:** tests/unit/test_compatibility.py reads files that 0.1.1, 0.2.0 and 0.6.0 wrote
  (tests/fixtures/0.x). Add the new release's files, generated from its tag, and never edit an old one
  to make a test pass.
