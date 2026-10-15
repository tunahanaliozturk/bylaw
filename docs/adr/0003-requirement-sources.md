# 0003: GitHub issues and repository Markdown as requirement sources

Status: Accepted, 2026-10-15

## Context

Requirement traceability is what sets bylaw apart, but requirements live in many tools: GitHub issues,
Markdown files, Jira, Azure DevOps, Confluence, Notion. Each extra source means another credential,
another API and another failure mode. bylaw is meant for anyone on GitHub.

## Decision

We read requirements from GitHub issues linked by closing keywords and from Markdown files in the
repository, and nothing else in v1.

## Consequences

- Both sources are reachable with the token the Action already has, so there is no extra setup.
- Acceptance criteria can be extracted deterministically from common Markdown shapes (task lists,
  "Acceptance criteria" headings, Given/When/Then), with model extraction marked `inferred` as a fallback.
- Cost: teams that keep requirements in Jira or Azure DevOps get no traceability until an adapter exists.
- Cost: issue comments are ignored, so a requirement refined in discussion is missed until someone edits
  the issue body.

## Alternatives

- **Jira and Azure DevOps from the start.** Lost on setup cost and on the extra credentials every user
  would have to manage. It would win if the first users were enterprise teams on those tools.
- **Issue body plus all comments.** Lost because comments are mostly discussion and noise that dilutes the
  criteria. It would win with a reliable way to tell agreed changes from discussion.
