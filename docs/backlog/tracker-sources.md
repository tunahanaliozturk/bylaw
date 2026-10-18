# Jira, Linear and Azure DevOps as requirement sources

Roadmap: Q2 in [ROADMAP.md](../ROADMAP.md). Target: v0.4. Item ids: `TRK-n`.

Many teams keep requirements outside GitHub. Read the work items a pull request references, with their acceptance criteria, the same way bylaw reads GitHub issues.

**Done when** a pull request that mentions `PROJ-123` or `AB#123` gets that work item's criteria in its summary.

## Items

- [x] **TRK-1** (M) Work item reference parser: `PROJ-123` (Jira), `AB#123` (Azure Boards), `LIN-123` (Linear). Done when: parser tests.
- [x] **TRK-2** (M) Jira Cloud REST read with an API token; opt-in base URL and allowed projects. Done when: fake server tests.
- [x] **TRK-3** (M) Azure DevOps work items with a PAT, including the Acceptance Criteria field. Done when: fake server tests.
- [x] **TRK-4** (M) Linear GraphQL read. Done when: fake server tests.
- [x] **TRK-5** (S) ADR on quoting tracker text in public comments, with an option to keep criteria text out of the summary. Done when: ADR accepted.
- [x] **TRK-6** (S) Setup docs per tracker. Done when: docs page.

## Notes

Reading needs a token for the tracker, and tracker text may end up in a public comment, so each tracker is an explicit opt-in with an allow list, like `issue_repos` (ADR 0007).

How it was built, and where it differs from the item text above:

- Linear keys are team keys, so `LIN-123` stands for any listed team (`ENG-123`). Jira and Linear keys share a shape; the allow lists decide which tracker a key belongs to, and one key cannot be listed for both.
- "Status only" in TRK-5 means the criterion's status in the review (met, partial, missing), not the work item's state in the tracker. Tracker states are not read.
- `AB#123` names no project, so the Azure Boards allow list is checked on the answer, after the read. ADR 0014 records that cost.
- After a security review: work items are read only for trusted authors unless `trackers_for_all_authors = true`; the review memory and the brief honour `quote_trackers = false`; missing and not-allowed work items share one note; config errors hide values; `@` in quoted prose cannot mention anyone. ADR 0014 records each.
- Every test runs against respx fakes built from the documented request and response shapes. Nothing below has been tried against a real account yet.

## Live checks before v1.0

These need real accounts and cannot run in CI. Each one should be tried once against a real tracker, with a throwaway token, on a private test repository, and the outcome written down here.

**Jira Cloud**

1. A pull request titled `PROJ-1: ...` with `[jira]` set and both variables present: the summary lists `PROJ-1/AC-n` rows from a description that has an "Acceptance criteria" heading with a bullet list.
2. The same with criteria written as Jira action items (the `/action` checklist), and with a numbered list: check the ADF node names and the `state` values (`TODO`, `DONE`) match what the converter expects.
3. A paragraph or rich text custom field named in `criteria_field`: check whether the API returns it as ADF or as a string, and that each line becomes a criterion.
4. Move an issue from a listed project to an unlisted one and reference its old key: the note says it moved, and no text from it appears anywhere.
5. A wrong token, an expired token and a key that does not exist: check the HTTP status in each note (401, 403 or 404) and that no note quotes Jira's message.
6. A site with a custom domain or one that redirects: the note says "redirect" and nothing is sent to the second host.

**Azure Boards**

1. `AB#n` for a User Story with both Description and Acceptance Criteria filled in, in a listed project: the criteria field's lines show up as `AB#n/AC-n`.
2. The same for a Task or an Issue (Basic process), which has no Acceptance Criteria field: check the request still succeeds without a `fields` list.
3. A work item in a project that is not listed: left out with the project note.
4. A token without the Work Items (Read) scope, and an expired one: check what status Azure DevOps sends. It may answer with a sign-in page (HTTP 203 with HTML) rather than 401; the note should say so either way.
5. Description HTML written in the web editor with nested lists, tables, images and links: check the Markdown is readable and the criteria are the right ones.

**Linear**

1. `ENG-n` with a description that has a checklist: the summary lists the items.
2. Confirm that `issue(id: "ENG-n")` resolves an identifier with a personal API key sent without `Bearer`, as the docs say.
3. Move an issue to a team that is not listed and reference the old identifier: left out with the team note.
4. A revoked key and a key with no access to the team: check the answer is an `errors` array with HTTP 200, or an HTTP error, and that the note quotes neither.

**All trackers**

1. Run the Action with the secrets passed as inputs, on a pull request from a branch and one from a fork: the fork run reports the variables as not set.
2. `quote_trackers = false`: read the posted summary, including its hidden state, and confirm no title, criterion text or note from a work item appears, and check whether the model's findings paraphrase criteria despite the `Quotable: no` instruction.
3. A pull request from an account that is not a member, under `pull_request_target`: the work items are not read and the note says why; with `trackers_for_all_authors = true` they are.
4. Check that the zero-width space after `@` stops a mention in a posted summary and still reads naturally.
5. Check the Actions log for the run: no token in it, and no tracker text beyond what the summary shows.
