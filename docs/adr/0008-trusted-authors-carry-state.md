# 0008: Only trusted authors' comments carry bylaw state

Status: Accepted, 2026-10-15. Refines 0005.

## Context

bylaw finds its own inline comments by a fingerprint marker and its summary by a summary marker, and it
keeps re-run state in the summary. Fingerprints are deterministic, so anyone who can comment on a pull
request, including its author, could post a comment with the marker of a security finding and make
bylaw believe it had already reported it, or post a fake summary with forged state. ADR 0005 also let a
resolved thread mute its finding, and a pull request author can resolve threads on their own pull
request.

## Decision

We treat a comment as bylaw's own, or as a maintainer's `bylaw: ignore`, only when its author is a bot or
has the `OWNER`, `MEMBER` or `COLLABORATOR` association, and a resolved thread no longer mutes a finding;
only `bylaw: ignore` from a trusted author does.

## Consequences

- A pull request author cannot hide a finding by planting markers or by resolving the thread.
- A finding whose thread a reviewer resolved while the problem is still present stays resolved but is
  listed in the summary under "Resolved by a reviewer but still present", so nothing disappears quietly.
- bylaw tracks only the threads it resolved itself (`auto_resolved`), so a finding that comes back
  reopens its thread.
- Cost: any bot can write a summary marker. A repository that runs a hostile bot has bigger problems,
  but the check is by account type, not by identity.

## Alternatives

- **Match the exact bot login.** Lost because the identity differs between `GITHUB_TOKEN`, a GitHub App
  and a personal token, and an installation token cannot ask who it is. It would win if bylaw shipped
  as a GitHub App with a fixed identity.
- **Keep resolve-to-mute from ADR 0005.** Lost because it lets the author silence their own review.
