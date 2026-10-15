# 0007: Issue references stay in the repository unless allow-listed

Status: Accepted, 2026-10-15

## Context

A pull request can name any issue with a closing keyword, including one in another repository
(`fixes otherorg/private#1`). From M2 on, the text of linked issues reaches a comment on the pull
request. With the default `GITHUB_TOKEN` bylaw cannot read other private repositories, but with a
personal token, or under `pull_request_target`, a pull request author could pull a private issue into a
public comment. The M1 review raised this and it was deferred until something was published.

## Decision

We read only issues in the pull request's own repository, plus repositories listed under `issue_repos`
in the base branch `.bylaw.toml`.

## Consequences

- A pull request cannot make bylaw copy text from a repository the maintainer did not name.
- A skipped reference is reported in the summary notes with the setting that enables it.
- Cost: projects that track work in a separate issues repository must add one line of configuration.

## Alternatives

- **Same owner only.** Lost because an organisation's private repository can still leak into a public
  one. It would win if bylaw only ever ran on private repositories.
- **Allow everything the token can read.** Lost because the token's reach is decided by whoever set up
  the workflow, not by the person reading the comment. It would win if comments were never public.
