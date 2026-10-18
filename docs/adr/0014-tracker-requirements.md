# 0014: Tracker work items as requirements, and what of them a public comment may quote

Status: Accepted, 2026-10-18. Amends 0003; follows 0007 and 0011.

## Context

ADR 0003 kept requirements to GitHub issues and Markdown in the repository, and named the cost: teams
that plan in Jira, Azure Boards or Linear got no traceability. Those trackers hold the acceptance
criteria for much of the work done on GitHub, and a pull request usually names its work item already
(`PROJ-123` in the title, `AB#123` in the body, a Linear identifier in the branch name).

Reading them brings two problems the GitHub issues did not have. The tracker needs its own token, which
the Action does not hold by default. And tracker text is usually private while the pull request may be
public: once bylaw puts a criterion in the summary comment, anyone who can read the pull request can read
it. ADR 0007 settled the same question for issues in other repositories with an allow list in the base
branch configuration.

## Decision

- **Opt-in per tracker, with an allow list, from the base branch.** `[jira]` names the site and the
  allowed project keys, `[azure_boards]` the organisation and the allowed projects, `[linear]` the
  allowed team keys. Without a table nothing is read from that tracker, and only keys of listed projects
  or teams count as references. `.bylaw.toml` is read from the base branch (ADR 0004), so a pull request
  cannot widen the list for itself.
- **References** come from the pull request title, body and commit messages. A key counts only when its
  project or team is listed, which is also what keeps `UTF-8`, `SHA-256` or `ISO-27001` from reading as
  work items. Digits are ASCII only, and keys inside HTML comments do not count, so the hidden examples
  of a pull request template are not fetched. At most ten work items are read per run, because the pull
  request text decides how many calls bylaw makes with the token.
- **Only for trusted authors, unless the repository says otherwise.** Work items are read only when the
  pull request's author is an `OWNER`, `MEMBER` or `COLLABORATOR`, the associations ADR 0008 trusts.
  Anyone else, such as a fork author under the `pull_request_target` recipe, could name ten allowed keys
  per push and have their text read into the review. For them a note says the work items were not read.
  `trackers_for_all_authors = true` reads them for every author, for repositories where that is fine. A
  local review (`bylaw context --base`) has no author and reads them as before.
- **The answer is checked as well as the reference.** Jira answers the key of a moved issue with the
  issue under its new key, and Linear resolves an old identifier after a team move, so the project or
  team in the answer must be on the list too. `AB#123` names no project at all, so for Azure Boards the
  project check can only happen on the answer: bylaw reads the work item, and if its project is not
  listed, the text is dropped before it reaches the review. The token's own reach is the outer limit.
- **Credentials only from the environment:** `JIRA_EMAIL` with `JIRA_API_TOKEN`, `AZURE_DEVOPS_TOKEN`,
  `LINEAR_API_KEY`. A token in `.bylaw.toml` is a configuration error, and no configuration error repeats
  the value it rejects, so a pasted token does not reach the Actions log; the message says to rotate it.
  Notes about failed reads carry the key and an HTTP status or a fixed phrase, never the exception text,
  the API's error message or the token, and a token an HTTP header cannot carry is a note too. Only HTTPS
  sites are accepted, and redirects are not followed, so the credentials cannot be sent on to another
  host.
- **Notes do not tell existence apart.** A work item that does not exist and one outside the allow list
  (moved to another Jira project or Linear team, or in an unlisted Azure DevOps project) get the same
  note, so a pull request author cannot use the notes to learn which keys exist in projects they were not
  given.
- **A failed read is a note, not a failed run.** A missing token, an unreachable tracker, a 404 or an
  answer that is not JSON leaves that work item out with a note in the summary, as an unreadable issue
  does.
- **Criteria** are extracted the same way as for issues. Jira's description (Atlassian Document Format)
  and Azure Boards' HTML fields are turned into Markdown first, keeping headings, lists and Jira action
  items. A dedicated criteria field (Azure Boards' Acceptance Criteria, or the Jira custom field named in
  `criteria_field`) becomes an "Acceptance criteria" section, one criterion per line. A work item with no
  structure gets inferred criteria (ADR 0011). Code blocks stay fenced and are never read as criteria,
  a table row reads as one line, and a list item continued after a line break or a second paragraph
  stays one criterion.
- **No mentions.** Quoted prose in bylaw's comments gets a zero-width space after every `@`, so a work
  item, an issue or the model cannot ping a person or a team. Code spans are left as written.
- **Quoting.** By default the summary quotes work item criteria as it quotes issue criteria. With
  `quote_trackers = false` the summary shows, for work items, only the criterion keys, their status and
  the code and test locations: no title, no criterion text, no inferred criterion text and no note from
  the reviewer, since a note often restates the criterion. The review memory in the summary's hidden
  state leaves out the same text and notes. The reviewer still reads the full text, so the review is as
  good either way, and the brief marks such a work item `Quotable: no` and tells the reviewer to refer
  to it by its labels only, never quoting or paraphrasing it in findings or scope notes.
- **What `quote_trackers = false` is for.** It guards against accidental quoting by bylaw and by an
  honest reviewer model. It is not a guard against a determined pull request author: text in the diff
  can ask the model to repeat a work item, and a model can paraphrase whatever it reads. The trust check
  above is what keeps outside authors away from the text; a repository whose tracker text must never
  appear in a pull request should not configure that tracker.

## Consequences

- A pull request that names `PROJ-123` or `AB#123` gets that work item's criteria in its summary, with
  the same checks as an issue.
- Work item text goes to the model provider, as issue text does (docs/privacy.md). A team whose tracker
  text may not reach a model provider should not configure a tracker.
- `quote_trackers = false` makes the summary harder to read: a reader has to open the work item to see
  what `PROJ-123/AC-2` means. That is the price of keeping the words private.
- Cost: `quote_trackers` controls what bylaw writes, and only asks the model. A requirement finding or a
  scope note written by the model can still paraphrase a criterion, by mistake or because the pull
  request asks it to.
- Cost: GitHub keeps the edit history of the summary comment, so turning `quote_trackers` off after
  work item text was posted does not remove the old revisions. The summary has to be deleted for that.
- Cost: a pull request from an outside contributor gets no work item criteria unless the repository
  sets `trackers_for_all_authors`.
- Cost: for Azure Boards, bylaw reads a work item before it knows whether its project is allowed. The
  text of a work item in a project that is not listed is read into memory and dropped, never into the
  context, the brief or a comment. A token scoped to the right projects avoids even that read.
- Cost: changing `quote_trackers` or a work item's text changes the requirements, so the next run is a
  full review (ADR 0012).
- Cost: one HTTP call per work item, at most ten per run; Jira Server and Data Center, Azure DevOps
  Server and Linear OAuth tokens are not supported yet.

## Alternatives

- **Never quote tracker text.** Lost because many teams use public pull requests with public trackers or
  private repositories with private trackers, where the text is useful in the summary and nothing leaks.
  It would win if most users ran bylaw on public repositories against private trackers.
- **Read every key the token can reach.** Lost for the reason ADR 0007 gives: whoever set up the
  token decides its reach, not the person reading the comment.
- **Ask for the Azure DevOps project in the reference, such as `AB#Fabrikam/123`.** Lost because nobody
  writes it: `AB#123` is the form the Azure Boards GitHub integration links, and a second form would be
  missed by the people it is meant to protect.
- **One generic adapter with configurable URLs and field paths.** Lost because each tracker differs in
  auth, rich text format and how it handles moved items, and those differences are where the security
  checks live.

API references used:
[Jira Get issue](https://developer.atlassian.com/cloud/jira/platform/rest/v3/api-group-issues/#api-rest-api-3-issue-issueidorkey-get),
[Jira basic auth](https://developer.atlassian.com/cloud/jira/platform/basic-auth-for-rest-apis/),
[Atlassian Document Format](https://developer.atlassian.com/cloud/jira/platform/apis/document/structure/),
[Azure DevOps Get Work Item 7.1](https://learn.microsoft.com/en-us/rest/api/azure/devops/wit/work-items/get-work-item?view=azure-devops-rest-7.1),
[Azure DevOps personal access tokens](https://learn.microsoft.com/en-us/azure/devops/organizations/accounts/use-personal-access-tokens-to-authenticate),
[Azure Boards field reference names](https://learn.microsoft.com/en-us/azure/devops/boards/queries/titles-ids-descriptions?view=azure-devops),
[AB# links from GitHub](https://learn.microsoft.com/en-us/azure/devops/boards/github/link-to-from-github),
[Linear GraphQL API](https://linear.app/developers/graphql),
[Linear schema](https://github.com/linear/linear/blob/master/packages/sdk/src/schema.graphql).
