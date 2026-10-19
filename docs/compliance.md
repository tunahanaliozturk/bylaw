# Compliance profiles

A compliance profile makes bylaw review a pull request with a standard's development controls in mind, tag
each finding with the controls it touches, and write down what happened to the change: the requirement it
links, the commit reviewed, the tests it changed, the findings and who accepted the ones left open. That
is evidence a team can show an auditor. It is not a verdict. bylaw does not make a repository, a team or
an organisation compliant, a pull request with no findings is not proof that a control was met, and the
tags are a reviewer's judgement, which can be wrong or incomplete. The reasons behind the design are in
[ADR 0021](adr/0021-compliance-profiles.md).

The first profile is `iso27001`, for the Annex A controls of ISO/IEC 27001:2022 that a code change can
touch.

## Turning it on

In `.bylaw.toml` on the default branch:

```toml
profiles = ["iso27001"]
```

The setting is read from the base branch, like every other one, so a pull request cannot switch the
profile off for itself; a pull request that changes `profiles` is reviewed with the old value until it
merges. A name bylaw does not know stops the review with a configuration error instead of quietly
reviewing without it, because a team that relies on the profile should find out about a typo at once.

In the GitHub App, an organisation can turn a profile on for every repository in the `.bylaw.toml` of its
`.github` repository. There, unlike every other setting, a repository's `profiles` adds to the
organisation's: a repository can add a profile but cannot drop one the organisation set. A repository
that is outside the scope of your certificate is better left out of the app's installation.

## What the `iso27001` profile covers

The profile lists these controls. The titles are bylaw's own short names, not the standard's wording, and
the guidance bylaw gives the reviewer for each is written in its own words as well:
[`src/bylaw/profiles/iso27001.toml`](../src/bylaw/profiles/iso27001.toml).

| Control | bylaw's title | Control | bylaw's title |
| --- | --- | --- | --- |
| 5.34 | Personal data protection | 8.24 | Cryptography |
| 8.3 | Restricting access to information | 8.25 | Secure development process |
| 8.4 | Source code access | 8.26 | Security requirements for applications |
| 8.5 | Authentication | 8.27 | Secure architecture |
| 8.8 | Technical vulnerabilities | 8.28 | Secure coding |
| 8.9 | Configuration | 8.29 | Security testing |
| 8.11 | Masking sensitive data | 8.31 | Separate environments |
| 8.12 | Preventing data leaks | 8.32 | Change management |
| 8.15 | Logs | 8.33 | Test data |

With the profile on:

- **The brief** gets the controls and their guidance, about 1,000 tokens. The reviewer reports problems as
  it always does, with the guidance as more places to look, and tags each finding with the control ids it
  touches, such as `8.28` for an SQL injection or `8.15` and `8.11` for an email address written to a log.
- **Validation** keeps only control ids the profile defines, reading `A.8.28` as `8.28`. A finding tagged
  with an id that does not exist keeps its place and loses the tag; the run's log says which id was
  dropped, cut to 20 characters. The finding itself is checked exactly as any other: on lines the change
  adds, with real evidence.
- **Severity rules** are applied by bylaw after validation, so the same tags always give the same
  severity. Under `iso27001`, a finding tagged both 8.15 and 8.11 (personal data or a secret in a log) is
  at least `high`, and a security finding tagged 8.24 (cryptography) is at least `high`. A rule never
  lowers a severity.
- **Inline comments** name the controls, and **the summary comment** gets two sections, described below.
- **The Action** uploads an evidence file per pull request.

## What it does not cover

- Anything that happens outside a pull request: risk assessment, access reviews, supplier management,
  incident handling, backups, physical security, and the rest of the management system.
- Approvals by people. bylaw does not read who approved a pull request; GitHub's review history and your
  branch protection rules are the record of that. The evidence says what bylaw reviewed, not who signed
  off.
- Deployment. Whether the reviewed commit is what reached production is for your release records.
- Completeness. A model reviewer can miss a problem, and a planted evaluation set (see below) measures how
  often on small, known changes, not on yours.
- The standard's text. ISO/IEC 27001:2022 and ISO/IEC 27002:2022 are copyright ISO and IEC, and nothing in
  bylaw quotes them. Read the controls in your own licensed copy.

## The summary comment

"Controls touched" lists, for each control a current finding names, where the finding is, its severity
and whether it is open or accepted. "No finding touches a control of the profile" means bylaw's review
found nothing to tag, which is worth recording, but is not a statement that the controls are met.

"Change management evidence" lists:

- **Requirements:** the issues, specs and work items the pull request links, with how many of their
  acceptance criteria the review judged met. "None linked" is itself useful: a change with no requirement
  behind it is the first thing a change-management sample asks about.
- **Reviewed:** the head commit and the base it was compared with, and whether the model answered on
  this run. When it did not, the Notes section says why: no key, the token budget, a fork in the app, or
  nothing changed since the last review, so the earlier model findings stand without a new call.
- **Tests changed:** the changed files that look like tests by their path, such as `tests/`, `test_*.py`,
  `*_test.go`, `*.test.ts`, Ruby's `spec/` and `*_spec.rb`, or `*Tests.cs`. A `testing` directory is not counted: several languages ship ordinary code under that name. Deleted tests are listed apart, as "Tests removed".
- **Findings:** how many are open, how many were accepted, and how many threads bylaw resolved this run
  because the problem is gone from the code.
- **Accepted:** each finding someone accepted, and how: muted by a maintainer's `bylaw: ignore` reply,
  with their login, or its thread resolved by a person while the problem is still in the code, with the
  login GitHub reports. Only owners, members and collaborators can mute a finding, and never on their own
  pull request.
- **Still open:** each finding whose thread the pull request's own author resolved. Resolving never
  mutes (ADR 0008), and an author cannot accept a finding on their own change, so these stay open: they
  count for `fail-on` and the evidence marks them `resolved_by_author`.

## The evidence file

`bylaw review --evidence PATH` writes the same record as JSON when a profile is on; without one it writes
nothing and says so. The Action passes it on every run and uploads the file as the workflow run's
artifact `bylaw-evidence-pr-<number>`, also when `fail-on` fails the check, because a failing review is
the one an auditor most wants to see. A later run of the same pull request writes its own artifact in its
own workflow run. Within one run the upload step sets `overwrite: true`, so a re-run attempt replaces the
file of the attempt before it instead of failing on the name.

With `--pr` or `--gitlab-mr`, `--evidence` needs `--post`: only a posting run reads the review threads,
and a file written without them would miss every mute and every resolve. With `--context`, for a local
change, there are no threads, so the file shows the change as a first run would see it.

Artifacts expire with the repository's retention setting, 90 days by default. If your certification
cycle needs the records longer, copy them to your own records store, for example with a scheduled
workflow that downloads the artifacts of merged pull requests. The GitHub App has no artifact store; there
the summary comment is the record.

On GitLab ([hosts.md](hosts.md)), add `--evidence bylaw-evidence.json` to the job's `bylaw review
--gitlab-mr` command and keep the file as a job artifact with `artifacts: paths: [bylaw-evidence.json]`
and `when: always`, so a job that `--fail-on` fails keeps it too. `repository` is then the project path
and `pull_request` the merge request's number.

### Schema, version 1

The file is one JSON object. `schema_version` changes when a field changes meaning or goes away; a new
field can be added within a version, so a reader should ignore fields it does not know.

| Field | What it holds |
| --- | --- |
| `schema_version` | `1`. |
| `bylaw_version` | The bylaw release that wrote the file. |
| `disclaimer` | One sentence: the record is evidence for an audit, not a compliance verdict. |
| `generated_at` | When the file was written, ISO 8601 in UTC. |
| `repository` | `owner/name`, or null for a review of a local change. |
| `pull_request` | The pull request number, or null for a local change. |
| `title` | The pull request title. |
| `base_sha` | The commit the change was compared with. |
| `head_sha` | The commit that was reviewed. |
| `profiles` | The profiles that were on: `name` and `standard`, such as `ISO/IEC 27001:2022, Annex A`. |
| `model_review` | Whether the model answered on this run. False when it was not called or failed, including when nothing changed since the last review and the earlier model findings were kept; `notes` says which. Null when the result came from outside `bylaw review`, such as a host model through `bylaw post`. |
| `requirements` | The linked requirements: `source`, such as `issue#12` or `PROJ-7`, and `criteria`, each a `key` and a `status` (`met`, `partial`, `missing` or `not assessed`). A requirement's title and text are never copied here. |
| `files_changed` | Every changed file bylaw read, each a `path` and its `status`: `added`, `modified`, `renamed` or `removed`. |
| `tests_changed` | The changed files that look like tests, in the same form. A `removed` test is coverage taken away, not added; the summary lists those as "Tests removed". |
| `findings` | Every current finding: `file`, `line_start`, `line_end`, `category`, `severity`, `message`, `evidence` (the rule line or criterion it cites, or null), `controls`, `status` (`open`, `accepted`, or `resolved_by_author` for one whose thread the pull request's author resolved, which still counts as open), and for one a person closed `how` (`muted` or `resolved`) and `by` (a login, or null when the host does not say). |
| `controls` | The controls the findings touch: `id`, `title` (bylaw's) and `findings`, each as `file:line`. |
| `threads_resolved` | Review threads bylaw resolved this run because their problem is gone from the code. |
| `notes` | The summary's notes: files skipped, rules read from the base branch, why the model review did not run. |

A shortened example:

```json
{
  "schema_version": 1,
  "bylaw_version": "0.6.0",
  "disclaimer": "bylaw records what its review saw: ...",
  "generated_at": "2026-10-19T12:00:00+00:00",
  "repository": "acme/payments",
  "pull_request": 42,
  "title": "Log failed sign-ins",
  "base_sha": "3f1c...",
  "head_sha": "9a7e...",
  "profiles": [{"name": "iso27001", "standard": "ISO/IEC 27001:2022, Annex A"}],
  "model_review": true,
  "requirements": [{"source": "issue#12", "criteria": [{"key": "issue#12/AC-1", "status": "met"}]}],
  "files_changed": [
    {"path": "app/auth.py", "status": "modified"},
    {"path": "tests/test_auth.py", "status": "modified"}
  ],
  "tests_changed": [{"path": "tests/test_auth.py", "status": "modified"}],
  "findings": [
    {
      "file": "app/auth.py", "line_start": 31, "line_end": 31, "category": "security", "severity": "high",
      "message": "The password is written to the log.", "evidence": null, "controls": ["8.15", "8.11"],
      "status": "open", "how": null, "by": null
    }
  ],
  "controls": [
    {"id": "8.15", "title": "Logs", "findings": ["app/auth.py:31"]},
    {"id": "8.11", "title": "Masking sensitive data", "findings": ["app/auth.py:31"]}
  ],
  "threads_resolved": 0,
  "notes": []
}
```

## How an auditor reads it

For a sampled change:

1. Open the pull request, or the evidence file from its last workflow run. Check `head_sha` against the
   commit that was merged: a review of an earlier commit does not cover what came after it.
2. Read `requirements`. A change with no linked requirement, or with criteria `missing`, is a question for
   the team about how the change was approved.
3. Read `model_review` and `notes`. A review that ran only bylaw's own checks covers formatting and the
   rules bylaw can check without a model, not secure coding. When the notes say the files were unchanged
   since an earlier review, the model findings come from that earlier commit's review.
4. Read `findings`. An open finding at `high` or above on a merged change, or an accepted one, should have
   a reason somewhere the team can show you: the thread on GitHub, a risk acceptance, a follow-up issue.
   `by` tells you whom to ask. A `resolved_by_author` finding was closed by the person who wrote the
   change; treat it as open.
5. Read `tests_changed` next to the code that changed. Security relevant code with no test change is
   worth a question, not a finding by itself.
6. Read who approved the pull request on GitHub. bylaw does not record it.

The record shows that a change was reviewed with the controls in mind and what the review said. Whether
that meets your Statement of Applicability is your judgement and your auditor's.

## How well it works

The evaluation set has planted cases for the profile: a change that writes a password to a log, a change
that hashes passwords with MD5, and a clean change in the same project. Each label names the controls a
right answer tags, and the report gives how many tagged findings named one of them. The numbers, per model
and date, are in [eval/README](eval/README.md).

## About this page

The numbering of the controls was checked against two public lists of the ISO/IEC 27001:2022 Annex A
controls, used for the numbering only:
[Open Security Architecture](https://opensecurityarchitecture.org/frameworks/iso-27001-2022) and
[ISMS.online](https://www.isms.online/iso-27001/annex-a-2022/), both read on 19 October 2026.

This page has not yet been reviewed by someone who has run an ISO/IEC 27001 audit. Until it has, read it as
the maintainers' understanding, and tell us in an issue where it is wrong.
