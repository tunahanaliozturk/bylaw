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

- A pull request author cannot hide a finding by planting markers or by resolving the thread, and a
  `bylaw: ignore` from the pull request's own author never counts, because `MEMBER` covers every member
  of an organisation, including people with read access only.
- bylaw finds its own marker as the last one in a comment and its state as the block that ends the
  summary, and it escapes markup in every string it did not write, so text in a finding, a spec or a
  file name cannot stand in for either.
- The summary is a trusted comment that opens with the marker, a bot's first; a comment that only
  quotes the marker is never edited.
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

## Amendment, 2026-10-19: the pull request's author never carries bylaw's state

The 1.0 security review found that the association check alone let a pull request's author hide a
finding when they are an organisation `MEMBER`, which GitHub gives to every member, read access or not.
Such an author could open a review thread whose first comment carried the fingerprint of a finding bylaw
was about to post: bylaw took the thread for its own, posted no inline comment, and the summary did not
list open threads, so the finding was shown nowhere. The same author could post a comment that opens with
the summary marker: bylaw used it as its summary when no bot had written one, edited that person's
comment, and read its `auto_resolved` list, so planted thread ids made bylaw reopen threads.

We now decide:

- A fingerprint counts only in a first comment by a trusted author who is not the pull request's author,
  unless that author is bylaw's own account: a trusted bot, the personal token's owner on GitHub, or the
  token's user on GitLab. This holds for a run and for the outcomes recorded when the pull request
  closes.
- On GitHub the summary is bylaw's own comment only: a trusted bot's, or, with a personal token, the
  token owner's, which bylaw learns from `GET /user` only when no bot has written a summary. A workflow
  or installation token cannot answer that call, so no person's comment is ever the summary, whatever
  their association; bylaw posts a new summary and leaves the person's comment alone. On GitLab, where
  bylaw already knows its account, the fallback for a token that cannot say who it is skips the merge
  request author's notes.
- The summary lists findings in open review threads under "Open in a review thread", so a finding is
  never only in a thread nobody opens.

Consequences:

- A pull request's author can still post comments with markers; they are ordinary comments.
- With a personal token on a pull request its owner opened, bylaw's comments are the author's comments.
  It tells them apart by asking who the token is, which costs one call, made only when such a comment
  carries a marker. Only a 401, a 404 or a 403 that is not a rate limit reads as "this token has no
  user"; any other failure of that call ends the run, because reading it as no identity would post a
  second summary and repost every open finding.
- Bots a pull request's author can steer. Trusting any bot means a bot that writes what a pull request
  asks for, such as a review bot that quotes the pull request or a workflow that echoes its text as
  `github-actions[bot]`, could plant a fingerprint or a summary. Where bylaw knows the bot it posts as,
  only that bot counts: the GitHub App names its own, and the Action sets `BYLAW_BOT_LOGIN` to
  `github-actions[bot]` when it posts with the workflow token. A workflow echoing pull request text as
  `github-actions[bot]` is still trusted then, so do not run one next to bylaw. With any other token, a
  personal token or an app token from another action, bylaw cannot name its bot and any bot counts;
  that is a known limit.
- Cost: a repository that ran bylaw with a personal token on 0.x and a person other than the token's
  owner wrote its summary gets a new summary comment on the first 1.0 run.

