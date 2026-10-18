# 0020: GitLab merge requests

Status: Accepted, 2026-10-19. Builds on 0001, 0004, 0005, 0007, 0008 and 0012.

## Context

ADR 0001 kept the core host-neutral so that only reading a change and publishing comments would differ
between hosts. GitLab is the second host. Its merge requests have the same parts as a pull request (a
diff, commits, a description, line comments that can be resolved, plain comments), but the API, the
roles and the CI runner differ in ways that touch the trust rules, not only the HTTP calls.

Every endpoint and field below was checked against GitLab's REST API v4 documentation on 2026-10-18:
[merge requests](https://docs.gitlab.com/api/merge_requests/),
[discussions](https://docs.gitlab.com/api/discussions/), [notes](https://docs.gitlab.com/api/notes/),
[repository files](https://docs.gitlab.com/api/repository_files/),
[repository tree](https://docs.gitlab.com/api/repositories/),
[project members](https://docs.gitlab.com/api/project_members/), [issues](https://docs.gitlab.com/api/issues/),
[the CI/CD job token](https://docs.gitlab.com/ci/jobs/ci_job_token/),
[the closing pattern](https://docs.gitlab.com/user/project/issues/managing_issues/#default-closing-pattern),
[quick actions](https://docs.gitlab.com/user/project/quick_actions/) and
[suggestions](https://docs.gitlab.com/user/project/merge_requests/reviews/suggestions/).

## Decision

`bylaw review --gitlab-mr <iid> --project <id or path>` reviews a merge request through the REST API with
a token in `GITLAB_TOKEN`, sent as `PRIVATE-TOKEN`. One object, `GitLabMergeRequest`, is both the source
and the publisher: it already holds the diff refs and the parsed diff that a positioned comment needs.
The core (context, validation, the plan, the summary and its state) is unchanged.

- **Reading.** The merge request (`diff_refs`), its diffs and commits, each paged by following the
  `Link: rel="next"` header. Base files are read with the raw file endpoint and directories with the tree
  endpoint at `diff_refs.start_sha`, the target branch commit. `base_sha` is the merge base: an author who
  branched from an old commit would bring old rules with them, which ADR 0004 rules out, and GitHub's base
  sha is the target branch head too. Positions still send all three shas.
- **Positioned discussions.** One discussion per inline finding, on the new side: `position_type: text`,
  the three shas, `old_path` (the old name of a renamed file), `new_path` and `new_line`. A finding over
  several lines adds a `line_range` whose line codes are computed as GitLab documents them
  (`<sha1 of the path>_<old>_<new>`, an added line keeping the old file's counter where it was inserted);
  if GitLab rejects the range with a 400, the comment is posted on its last line alone. GitLab has no
  review that groups comments, so the review body GitHub gets is not posted.
- **Suggestions.** GitLab applies a plain `suggestion` block to the commented line only, so a finding over
  several lines gets `suggestion:-N+0`, or applying it would replace one line with all of them.
- **Quick actions.** GitLab runs `/merge`, `/approve`, `/close` and the rest from any note line that starts
  with a slash, as the token's user. Text from the model, the merge request and issues reaches those
  lines, so bylaw puts a zero-width space in front of every such line before posting. Only bylaw's own
  suggestion block is left as written: it is always a fenced code block, where GitLab reads no quick
  action. Other code blocks get the space too, because telling them apart exactly as GitLab's Markdown
  does is where a mistake would hide.
- **Summary note.** One note that starts with the summary marker, edited in place with `PUT`, with the
  hidden state at its end (ADR 0005). GitLab strips trailing whitespace and carriage returns from a note
  body; the state block does not depend on either.
- **Resolving.** `PUT .../discussions/:id?resolved=true|false`. A discussion counts as resolved when all
  of its resolvable notes are.
- **Trust (ADR 0008).** GitLab has no author association on a note, so bylaw asks the members API for the
  author's highest role in the project, inherited and invited roles included, once per author. A note
  is trusted when its author is bylaw's own account or has the Developer role or higher (access level
  30), the roles that can push code, which is what GitHub's write access means. Reporters and Guests can
  comment but are not trusted, and the merge request author's `bylaw: ignore` still never counts. The
  author of the merge request is trusted for tracker reads (ADR 0014) on the same rule.
- **Review memory (ADR 0012).** GitLab can say who a token is (`GET /user`), which the Action's
  `GITHUB_TOKEN` cannot, so the memory is trusted only in a summary written by that exact account, not by
  any bot, as the GitHub App does with its own login (ADR 0017). A summary by a Developer is still used for mutes and resolved threads, with a full review. A token
  that cannot say who it is trusts no memory.
- **Closing issues (GLB-3).** The union of what `GET .../closes_issues` returns, which follows a
  self-managed instance's own pattern, and what GitLab's default closing pattern finds in the title,
  description and commit messages, because GitLab lists nothing for a merge request into a branch other than the
  default one. References are `#12`, `lib#12` (a project in the same namespace), `group/sub/lib#12` and
  issue links on the same instance. ADR 0007's allow list applies unchanged, by full project path.
- **Issues.** The title, the description and the comments of Developers and above, newest first, at most
  20 and 8,000 characters as on GitHub. System notes and internal notes are never read, and a
  confidential issue is left out entirely: its text would land in a summary more people can read.
- **CI.** `docs/recipes/gitlab-ci.yml` runs on `merge_request_event` pipelines with
  `uvx bylaw@<version>`, `CI_API_V4_URL`, `CI_MERGE_REQUEST_IID` and `CI_MERGE_REQUEST_PROJECT_ID`, and
  a project access token in `GITLAB_TOKEN`. `CI_JOB_TOKEN` can read a merge request and its notes but not
  its diffs, and it cannot post, so it is not enough.

## Consequences

- A GitLab merge request gets inline discussions and a summary note, and a re-run behaves as on GitHub.
  The fake server tests cover reading, positions, line ranges, the fallback, suggestions, quick actions,
  the summary, trust and a re-run that resolves a fixed finding.
- A merge request from a fork runs its pipeline in the fork, without the project's variables. bylaw sees
  no token there, prints a note and exits with success, as it does on GitHub.
- Cost: one members call per distinct note author, cached per run. An issue with many outside commenters
  costs a call per commenter until 20 trusted comments are found.
- Cost: the token variable cannot be protected, because merge request pipelines run on unprotected
  branches. Anyone who can push a branch can read it in a job. That is a Developer, who can already
  push code and comment with their own account, but with the token they could also post a summary as
  bylaw's account with a forged review memory, so the next run skips files it should have read. Use a
  dedicated token with nothing but the Developer role, and rotate it if a job ever prints it.
- Cost: reading many base files at once is one request per file; GitLab's GraphQL `repository.blobs`
  could batch them if that turns out to be slow.
- Cost: GitLab caps `changes_count` at the string `"1000+"`, so a very large merge request gets no note
  that its listing was cut.
- Not covered yet: `bylaw context` and `bylaw post` (the Claude Code and Codex path) read GitHub only, and
  the live checks listed in docs/backlog/gitlab.md have not run against gitlab.com.

## Alternatives

- **`--host gitlab` with `--pr` meaning a merge request.** Lost because `--pr` and `--repo` would mean
  different things by host, and a GitHub run must not change. `--gitlab-mr` and `--project` say what they
  are, and `--project` defaults to the CI variables.
- **Read base files at `diff_refs.base_sha`.** Lost for the reason above. It would win if the diff and the
  rules had to come from one commit, as for the evaluation snapshots of ADR 0015.
- **Trust any bot account, as on GitHub.** Lost because GitLab's note author carries no bot flag, and
  because GitLab can name bylaw's own account, which is stronger.
- **Detect code blocks before neutralising quick actions.** Lost because a mismatch with GitLab's Markdown
  parser would let a quick action through, while an extra zero-width space in a code block only shows.
- **GraphQL for everything.** Lost because REST covers every call with fewer moving parts. It would win
  for batched file reads.
