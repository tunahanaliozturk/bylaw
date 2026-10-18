# Jira, Linear and Azure DevOps as requirement sources

Roadmap: Q2 in [ROADMAP.md](../ROADMAP.md). Target: v0.4. Item ids: `TRK-n`.

Many teams keep requirements outside GitHub. Read the work items a pull request references, with their acceptance criteria, the same way bylaw reads GitHub issues.

**Done when** a pull request that mentions `PROJ-123` or `AB#123` gets that work item's criteria in its summary.

## Items

- [x] **TRK-1** (M) Work item reference parser: `PROJ-123` (Jira), `AB#123` (Azure Boards), `LIN-123` (Linear). Done when: parser tests.
- [x] **TRK-2** (M) Jira Cloud REST read with an API token; opt-in base URL and allowed projects. Done when: fake server tests.
- [x] **TRK-3** (M) Azure DevOps work items with a PAT, including the Acceptance Criteria field. Done when: fake server tests.
- [x] **TRK-4** (M) Linear GraphQL read. Done when: fake server tests.
- [ ] **TRK-5** (S) ADR on quoting tracker text in public comments, with an option to keep criteria text out of the summary. Done when: ADR accepted.
- [ ] **TRK-6** (S) Setup docs per tracker. Done when: docs page.

## Notes

Reading needs a token for the tracker, and tracker text may end up in a public comment, so each tracker is an explicit opt-in with an allow list, like `issue_repos` (ADR 0007).
