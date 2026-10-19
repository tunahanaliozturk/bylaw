# 0021: Compliance profiles add guidance, tags and evidence, never a verdict

Status: Accepted, 2026-10-19. Builds on 0004, 0005, 0012 and 0017.

## Context

Teams certified under ISO/IEC 27001 list, in their Statement of Applicability, the Annex A controls they
apply. Several of them are about how software changes: secure coding, use of cryptography, logging, data
masking, change management. At audit time the team has to show, for a sample of changes, that those
controls were applied: who reviewed the change, what was found, what was done about it, and whether
tests changed with the code. That evidence usually lives in people's heads, in pull request threads and
in a spreadsheet filled in before the audit.

bylaw already reviews every pull request and keeps a record of what it found in the summary comment
(ADR 0005). With a little more it could review with the team's controls in mind, say which control a
finding touches, and leave a record per pull request that an auditor can read. The risks are three:
claiming more than a code reviewer can know, copying a standard that is copyrighted, and letting a pull
request switch the profile off for itself.

## Decision

- **A profile is a file shipped inside bylaw.** `src/bylaw/profiles/<name>.toml` names the standard and
  its edition, and lists controls: an id, a short title and guidance for the reviewer, all in bylaw's own
  words. It may add severity rules (below). The first is `iso27001`, with the development related
  controls of ISO/IEC 27001:2022 Annex A: 5.17, 5.34, 8.2 to 8.5, 8.8 to 8.12, 8.15, 8.16, 8.24 to 8.29
  and 8.31 to 8.33, the ones bylaw can look for in a diff. A repository cannot define or edit a
  profile: the controls and rules are part of bylaw's version, reviewed like its code, so a change
  cannot redefine what a control means to pass.
- **The standard's text is never copied.** ISO/IEC 27001:2022 and ISO/IEC 27002:2022 are copyrighted
  by ISO and IEC. A profile carries the control numbers, a short title bylaw wrote for each and bylaw's
  own reviewer guidance, which says what to look for in code, not what the control says. Some short
  titles match the standard's own short names ("Secure coding"), because that is what the practice is
  called; no sentence of the standard is copied. The profile
  file's header says so. A team that needs the wording reads its own licensed copy. The numbering was
  checked against two public lists of the 2022 Annex A controls, and those lists are cited in the profile
  for the numbering only, not as a source of text.
- **What bylaw claims.** It reviews each pull request with the profile's guidance, tags findings with the
  controls they touch, raises the severity of some findings by fixed rules, and writes down what happened:
  the requirement linked, the commit reviewed, the tests changed, the findings and who accepted the ones
  left open. That is evidence that a control was applied to a change. **What it does not claim:** that a
  repository, a team or an organisation is compliant or certifiable, that a change with no findings meets
  a control, that the tags are complete, or that a person approved the change. A model reviewer can miss
  a problem and can tag one wrongly, so the record says what bylaw saw, never what the auditor should
  conclude. The docs page says this in the first paragraph, and the summary and the evidence file say it
  in one line each.
- **Switched on from the base branch.** `profiles = ["iso27001"]` in `.bylaw.toml`, read from the base
  branch like every setting (ADR 0004), so a pull request cannot turn a profile off for itself. A name
  bylaw does not know is a configuration error, not a warning: a team whose auditor relies on the profile
  must not get a review without it because of a typo.
- **Organisation defaults are a floor in the GitHub App.** An organisation that turns a profile on in its
  `.github` repository's `.bylaw.toml` (ADR 0017) means every repository. Unlike every other key, a
  repository's `profiles` adds to the organisation's instead of replacing them, so a repository can add
  a profile but not drop the organisation's.
- **The brief.** When a profile is on, the brief gets a `profiles` block after the decisions: per control
  its id, title and guidance, about 1,000 tokens for `iso27001`. Without a profile the block is not there
  and the brief is unchanged.
- **Findings carry `controls`.** A finding may name control ids, such as `["8.28"]`. In the model's
  schema the field is required, an empty list when no profile is on or none applies, because strict
  structured outputs need every field required. Validation drops the ids the active profiles do not
  define and keeps the finding, with a line in the dropped list. A wrong tag is a labelling error, not a
  sign the problem is invented: the finding has already passed the same checks as any other, and
  dropping a real SQL injection because the reviewer tagged it `8.99` would hide the problem to keep the
  record tidy.
- **Severity rules are applied by bylaw, not the model.** After validation, a rule raises the severity of
  a finding that carries all the rule's controls (and its category, when the rule names one) to the
  rule's minimum. It never lowers one. In `iso27001`: a finding tagged both logging (8.15) and data
  masking (8.11), which the guidance asks for when personal data or a secret reaches a log, is at least
  `high`; a security finding tagged cryptography (8.24) is at least `high`. The rules depend on the tags
  the reviewer chose, so they are only as good as the tags, but the same tags always give the same
  severity, and the test suite pins every rule.
- **Incremental review.** The profile names and each profile file's content are part of the inputs key
  (ADR 0012), so turning a profile on, or a new edition of it, forces a full review.
- **The summary.** With a profile on, the summary gets a "Controls touched" table, the controls the
  current findings name with where, and a "Change management evidence" list: the linked requirements and
  their criteria, the commit reviewed and whether the model answered on this run (a flag the run sets,
  never read from note text), the test files the change touches or removes, and the findings resolved,
  still open, or accepted, with who accepted them. The notes come before these sections, so a summary
  cut to GitHub's size limit keeps them. Who comes from data bylaw already reads: the login of the maintainer whose `bylaw: ignore` reply muted a finding, and
  GitHub's `resolvedBy` on a thread a person resolved, one more field in the threads query bylaw already
  makes (GitLab's `resolved_by` on the thread's notes). A thread the pull request's own author resolved
  accepts nothing: resolving never mutes (ADR 0008), so such a finding stays open, counts for
  `fail-on`, and is marked `resolved_by_author`. Before this, an author could take a finding out of
  `fail-on` by resolving its thread; that gap is closed for every repository, profile or not.
- **The evidence file.** `bylaw review --evidence PATH` writes the same record as JSON when a profile is
  on, with a `schema_version` that changes when a field changes meaning or goes away; new fields may be
  added within a version. The Action passes `--evidence` and uploads the file as an artifact of the
  workflow run with `actions/upload-artifact`, pinned by commit like the Action's other steps, even when
  `fail-on` fails the check. Without a profile no file is written and nothing is uploaded. With `--pr` or
  `--gitlab-mr` the file needs `--post`, because only a posting run reads the threads that say what was
  muted or resolved. A fork's or Dependabot's run without secrets is skipped whole, evidence included.
  The summary and the file read the same plan, notes included. The GitHub App has nowhere to upload a
  file, so there the summary comment is the record.

## Consequences

- An auditor can pick a pull request and read, in its summary or its artifact, which controls bylaw saw
  touched, what it found and who accepted what. docs/compliance.md explains how to read it and what it
  does not prove.
- Cost: about 1,000 more input tokens per review with `iso27001` on; nothing without a profile.
- Cost: every finding in the model's answer has one more field, `controls`, which is `[]` for most
  repositories. A local model that leaves it out gets the JSON fallback's one retry (ADR 0018).
- Cost: artifacts expire with the repository's retention setting, 90 days by default. A team that keeps
  evidence for its certification cycle has to copy the files to its own records store; the docs say so.
- Cost: the tags are the reviewer's judgement. Planted evaluation cases measure whether they come out
  right, and a clean case checks that a profile does not invent findings.
- Not covered: approvals by people, branch protection, deployment, access reviews and everything else in
  the standard that happens outside a pull request. bylaw does not read reviews or approvals; the
  auditor reads them on GitHub.
- The format takes further profiles (SOC 2, PCI DSS requirement 6, OWASP ASVS, GDPR, KVKK) without code
  changes; each needs its own licensing check before any wording is written.

## Alternatives

- **Quote the controls.** Lost because the text is ISO's and IEC's to license, and a public repository
  would be redistributing it. It would win only with a licence from ISO.
- **Profiles in the repository, as `.bylaw/profiles/*.toml`.** Lost for now because a profile defines
  what counts as a severe finding: a repository could weaken its own rules, and every repository would
  maintain its own copy of the same controls. It could come later for organisations with their own
  control sets, read from the base branch.
- **Drop the finding when a control id is unknown.** Lost because the tag is the least certain part of a
  finding and the problem is the most important; see the decision above.
- **Ask the model to apply the severity rules.** Lost because the same finding could come out `high` in
  one run and `medium` in the next, and an auditor needs to know the rule was applied every time.
- **A repository's `profiles` replaces the organisation's, as other keys do.** Lost because a profile is
  a policy the organisation sets for its scope, and one repository opting out would leave a hole in it
  that nobody sees. A repository outside the scope can be left out of the app's installation.
- **Evidence as a check run or a commit status.** Lost because those hold a summary, not a document an
  auditor can download, and the summary comment already gives the readable view.
- **A control field per finding chosen from an enum in the schema.** Lost because the enum would change
  with the profiles a repository turns on, so the schema would differ per repository and break the
  prompt cache; validation against the active profiles does the same job.
