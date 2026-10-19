# Jira, Azure Boards and Linear

bylaw can read the work items a pull request names in Jira Cloud, Azure Boards or Linear and check the
change against their acceptance criteria, the same way it checks linked GitHub issues. The criteria show
up in the summary comment next to the issues and specs.

Each tracker is off until you turn it on, and three things have to be in place:

1. A table for the tracker in `.bylaw.toml` on the **base** branch, with an allow list of projects or
   teams. bylaw reads the base branch copy, so a pull request cannot add a project for itself.
2. A token in the environment. Tokens are never read from `.bylaw.toml`; putting one there is a
   configuration error, because that file is public in a public repository.
3. A reference in the pull request **title, body or a commit message**: `PROJ-123` for Jira, `AB#123`
   for Azure Boards, `ENG-123` for Linear.

Work items are read only for pull requests whose author is an owner, member or collaborator of the
repository. Anyone else could name allowed keys to have their text read, so for them a note says the
work items were not read. If outside contributors should get work item criteria too, and the tracker
text may be read for them, add `trackers_for_all_authors = true`. A local review of a branch
(`bylaw context --base`) has no author and always reads them.

Why the allow list: tracker text is often private while the pull request may be public, and the summary
quotes the criteria it checks. The list says which projects the maintainers agreed may be read, whatever
else the token can reach ([ADR 0014](adr/0014-tracker-requirements.md)).

## What counts as a reference

Only a key whose project or team is listed. With `projects = ["PROJ"]`, `PROJ-123` is a reference, while
`UTF-8`, `SHA-256`, `ISO-27001` and `OTHER-5` are not. Keys are upper case, as the trackers write them.
A key inside a link (`https://acme.atlassian.net/browse/PROJ-123`) or a branch name in a merge commit
(`feature/PROJ-123-login`) counts too. A key inside an HTML comment (`<!-- for example PROJ-1 -->`, as
pull request templates often have) does not.

At most ten work items are read per run. The rest are named in a note.

## Where the criteria come from

- A checklist (`- [ ] ...`, or Jira action items) anywhere in the text.
- List items under a heading such as "Acceptance criteria" or "Requirements", and Given/When/Then blocks.
- A dedicated field: Azure Boards' **Acceptance Criteria**, or the Jira custom field you name in
  `criteria_field`. Every line of that field is one criterion, so a field written as plain lines works.

A work item with none of these is checked like a prose issue: the reviewer derives up to five criteria
and the summary marks them "(inferred)" ([ADR 0011](adr/0011-inferred-criteria-and-maintainer-comments.md)).
Comments on work items are not read.

## Jira Cloud

```toml
[jira]
url = "https://acme.atlassian.net"     # your site, https only
projects = ["PROJ", "OPS"]             # project keys a pull request may name
criteria_field = "customfield_10042"   # optional: the field that holds acceptance criteria
```

Environment: `JIRA_EMAIL` (the account's email address) and `JIRA_API_TOKEN`.

1. Use an account that can browse the listed projects and nothing more, if you can: a bot account in a
   group with **Browse projects** on those projects.
2. Create an API token for it at <https://id.atlassian.com/manage/api-tokens>.
3. To find the criteria field id, list your site's fields with
   `curl -u "$JIRA_EMAIL:$JIRA_API_TOKEN" https://acme.atlassian.net/rest/api/3/field` and look for
   the field by its name; its `id` (such as `customfield_10042`) is the value. Leave `criteria_field`
   out if you keep criteria in the description.

bylaw reads the summary, the description and the criteria field through the
[REST API v3](https://developer.atlassian.com/cloud/jira/platform/rest/v3/api-group-issues/#api-rest-api-3-issue-issueidorkey-get)
with [basic auth](https://developer.atlassian.com/cloud/jira/platform/basic-auth-for-rest-apis/).
An issue that has moved to a project outside the list is left out, even when its old key still works.
Jira Server and Data Center are not supported yet.

## Azure Boards

```toml
[azure_boards]
organization = "acme"                  # dev.azure.com/acme
projects = ["Fabrikam", "Payments"]    # projects whose work items may be read
```

Environment: `AZURE_DEVOPS_TOKEN`.

1. Create a [personal access token](https://learn.microsoft.com/en-us/azure/devops/organizations/accounts/use-personal-access-tokens-to-authenticate)
   in the organisation with the **Work Items (Read)** scope only, and as short an expiry as you can
   manage. A token from an account that can see only the listed projects is best.
2. Reference work items as `AB#123`, the form the
   [Azure Boards GitHub integration](https://learn.microsoft.com/en-us/azure/devops/boards/github/link-to-from-github)
   uses. Note that the integration itself ignores `AB#` in a pull request title; bylaw reads it there too.

bylaw reads the title, the description and the Acceptance Criteria field through
[Get Work Item](https://learn.microsoft.com/en-us/rest/api/azure/devops/wit/work-items/get-work-item?view=azure-devops-rest-7.1).
`AB#123` names no project, so bylaw checks the project after reading the work item and drops it if the
project is not listed; that is why a token limited to the right projects matters most here. Azure
DevOps Server is not supported yet.

## Linear

```toml
[linear]
teams = ["ENG", "WEB"]                 # team keys, the part before the dash in ENG-123
```

Environment: `LINEAR_API_KEY`.

1. Create a personal API key under **Settings > Security & access** in Linear, preferably from an
   account that is a member of the listed teams only. If Linear offers to limit the key's permissions,
   give it read access only.
2. A team key cannot be listed for both Jira and Linear; bylaw would not know which tracker `ENG-12`
   belongs to.

bylaw reads the title and the Markdown description through the
[GraphQL API](https://linear.app/developers/graphql). An issue moved to a team outside the list is left
out.

## In the GitHub Action

Store the tokens as repository or organisation secrets and pass them as inputs:

```yaml
      - uses: tunahanaliozturk/bylaw@v0
        with:
          api-key: ${{ secrets.ANTHROPIC_API_KEY }}
          jira-email: ${{ secrets.JIRA_EMAIL }}
          jira-api-token: ${{ secrets.JIRA_API_TOKEN }}
          azure-devops-token: ${{ secrets.AZURE_DEVOPS_TOKEN }}
          linear-api-key: ${{ secrets.LINEAR_API_KEY }}
```

Pass only the ones you use. A `pull_request` run from a fork gets no secrets, so its work items are left
out with a note. Under the [`pull_request_target` recipe](recipes/pull-request-target.yml) the secrets are
there, but a fork author is usually not a member, so work items are still not read for them unless
`trackers_for_all_authors = true`.

From a terminal, set the same variables before `bylaw context` or `bylaw review --pr`.

## When an agent picks the repository

The site a token goes to comes from `.bylaw.toml`, and that file belongs to the repository being
reviewed. In the Action that is your own repository. When an agent chooses the repository, it is not:
a pull request can ask the agent to review `attacker/x`, whose `.bylaw.toml` names the attacker's Jira,
and your token would go there. So in three places the site must also be pinned in the environment:

- `bylaw mcp`, for pull requests and local branches alike;
- `bylaw context --pr` with a `--repo` other than `GITHUB_REPOSITORY`, which is how the Claude Code and
  Codex skill runs it;
- `bylaw review --pr` with a `--repo` other than `GITHUB_REPOSITORY`, for the same reason: whoever
  picks the repository is not its owner.

There, set `JIRA_URL` (for example `https://acme.atlassian.net`) and `AZURE_DEVOPS_ORGANIZATION` next to
the tokens. A work item is read only when `.bylaw.toml` names that same site; otherwise, or when the
variable is not set, it is left out with a note and the token is sent nowhere. Linear has one fixed host,
so its key needs no pin. The GitHub App works the same way (ADR 0017); the MCP server and the skill's
path are in ADR 0019.

## Keeping tracker text out of comments

By default the summary quotes work item criteria like issue criteria. If your tracker is private and
your pull requests are public, add this to `.bylaw.toml`:

```toml
quote_trackers = false
```

The summary then shows, for work items, only the criterion keys (`PROJ-123/AC-2`), their status and the
code and test locations: no title, no criterion text and no reviewer note. The reviewer still reads the
full text, so the review itself does not get worse. The hidden review memory at the end of the summary
leaves out the same text, so it does not hide there either. What this does not cover: a finding the model writes
in its own words can still paraphrase a criterion. [ADR 0014](adr/0014-tracker-requirements.md) explains
the trade-off. In short, `quote_trackers = false` guards against accidental quoting. It is not a guard
against a determined pull request author, whose diff can ask the model to repeat a work item, or against
the model paraphrasing what it read; the brief tells the model not to, which is a request, not a
guarantee. Keeping outside authors away from the text is the job of the author check above.

Set it before the first review that names a private work item. GitHub keeps the edit history of a
comment, and bylaw edits one summary comment in place, so switching to `false` later hides the text from
the current summary but not from its earlier revisions. Delete the summary comment (bylaw writes a new
one on the next run) if old revisions must go.

Work item text also goes to the model provider, as issue text does ([privacy.md](privacy.md)).

## When something is left out

Every work item that was referenced but not used gets a line under **Notes** in the summary, saying why:
the author is not trusted, the token is not set or has characters an HTTP header cannot carry, the
tracker answered with an HTTP error or a redirect (bylaw never follows one with credentials), or more
than ten were named. A work item that does not exist and one outside the allow list get the same note,
"could not read, or it is outside the allow list", so the notes do not reveal which keys exist in other
projects. The note carries the key and the reason, never the token or the tracker's own error text. The
review goes on without the item.

If `.bylaw.toml` itself is invalid, the error names the setting but never its value. If you put a token
in the file by mistake, remove it and rotate the token: the file is public in a public repository, and
its history keeps the old value.
