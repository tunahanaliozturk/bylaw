# GitLab merge requests

Roadmap: Q3 in [ROADMAP.md](../ROADMAP.md). Target: v0.6. Item ids: `GLB-n`.

The core is host-neutral (ADR 0001); only reading the change and publishing comments differ. The design is [ADR 0020](../adr/0020-gitlab.md).

**Done when** a GitLab merge request gets inline discussions and a summary note, with re-runs behaving as on GitHub.

## Items

- [x] **GLB-1** (M) Source: merge request diff, base files, notes. Done when: fake server tests.
- [x] **GLB-2** (L) Publish: positioned discussions, resolve, summary note with state. Done when: fake server tests.
- [x] **GLB-3** (M) Closing patterns and issue reading. Done when: tests.
- [x] **GLB-4** (S) `.gitlab-ci.yml` template. Done when: template tested on a demo project. The template's command is tested against the fake server; the run on a real project is the first of the live checks below.

## Live checks before v1.0

Everything above is tested against a fake GitLab built from the API documentation. These need a real gitlab.com project, a project access token and a second account; tick each one when it has been seen working.

- [ ] The recipe as written (`docs/recipes/gitlab-ci.yml`) runs on a merge request pipeline in the `ghcr.io/astral-sh/uv:python3.13-bookworm-slim` image and posts.
- [ ] `GET /user` with a project access token returns its bot user, so the summary is recognised as bylaw's own and the second run is incremental.
- [ ] A project access token with the Developer role can read `/projects/:id/members/all/:user_id` for another member, and gets a 404 for a non-member.
- [ ] `CI_JOB_TOKEN` in `GITLAB_TOKEN` fails with a clear 401 or 403 on the diffs, as the job token documentation says.
- [ ] A single-line discussion lands on the right added line of a modified file, a new file and a renamed file (`old_path` is the old name).
- [ ] A multi-line finding shows "Comment on lines +a to +b", which proves the computed line codes; if GitLab rejects them, the comment still lands on the last line.
- [ ] A suggestion on a multi-line finding applies to the whole range (`suggestion:-N+0`) and a single-line one to its line.
- [ ] A finding message with a line `/close` posts as text and closes nothing; the zero-width space is invisible.
- [ ] The summary note is edited in place on the second run, and its hidden state survives GitLab's note normalisation.
- [ ] Fixing a finding resolves its discussion; bringing it back reopens it; `bylaw: ignore` from a Maintainer mutes it, and from a Reporter or the author does not.
- [ ] After a push that moves the commented line, the discussion's `position` follows it, and one on a deleted line is reported on its old head (outdated).
- [ ] `closes_issues` lists `Closes #1` and `Fixes group/other#2` for a merge request into the default branch, and nothing for one into another branch, where the description's pattern still finds them.
- [ ] Internal notes and system notes on an issue are not quoted, and a confidential issue is left out with a note.
- [ ] A merge request from a fork runs its pipeline in the fork, where bylaw prints its note and exits 0.
- [ ] For a fork, files at the head sha are readable through the target project (`read_head` for specs).
- [ ] The token variable, masked and not protected, reaches a merge request pipeline on an unprotected branch, and the job runs with `GIT_STRATEGY: none` (no checkout).
- [ ] A finding whose line GitLab refuses as a position is posted as an unpositioned discussion naming the line, and the summary still updates.
- [ ] A finding message with `\r/approve` approves nothing.
- [ ] A Developer's note that starts with the summary marker is left alone: bylaw posts its own summary next to it.
- [ ] A self-managed instance under a relative URL (`https://host/gitlab/api/v4`) resolves issue links.

## Notes

Bitbucket only if users ask.

`bylaw context`, `bylaw post` and `bylaw mcp`, which agents use, still read GitHub only.
