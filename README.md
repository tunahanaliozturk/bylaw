<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/tunahanaliozturk/bylaw/main/docs/images/wordmark-dark.svg">
    <img src="https://raw.githubusercontent.com/tunahanaliozturk/bylaw/main/docs/images/wordmark-light.svg" alt="bylaw" width="236">
  </picture>
</p>

<p align="center">
  Pull request review against your repository's own rules and the requirements the change claims to implement.
</p>

<p align="center">
  <a href="https://github.com/tunahanaliozturk/bylaw/actions/workflows/ci.yml"><img src="https://github.com/tunahanaliozturk/bylaw/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/licence-MIT-blue" alt="MIT licence"></a>
  <img src="https://img.shields.io/badge/python-3.13%2B-blue" alt="Python 3.13+">
</p>

Most AI reviewers give general advice. bylaw reviews a pull request against what your repository already wrote down:

- **Your rules.** `.editorconfig`, linter configs, `CONTRIBUTING.md`, `AGENTS.md`, including a package's own in a monorepo. Every rule finding cites the line it comes from, or a linter rule id your configuration enables, such as `ruff:S608`.
- **Your decisions.** The accepted ADRs in `docs/adr/`. A change that goes against one gets a finding that cites the line of the decision it contradicts; superseded and proposed ADRs are left alone.
- **Your requirements.** The acceptance criteria in the issues the pull request closes and the specs it links, including what maintainers added in the issue's comments. An issue written as prose gets criteria inferred from its text, marked as such. The summary says which are met, partly met or missing, and flags changes nobody asked for.
- **Security and bugs.** Injection, secrets, unsafe deserialisation, missing authorisation, and plain bugs.

Findings go on the changed lines as review comments. A re-run never repeats a comment and resolves the threads of findings that were fixed.

## What a review looks like

Real output on [bylaw-demo pull request 7](https://github.com/tunahanaliozturk/bylaw-demo/pull/7). An inline finding with its rule citation and a one-click fix:

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/tunahanaliozturk/bylaw/main/docs/images/screenshot-inline-dark.png">
  <img src="https://raw.githubusercontent.com/tunahanaliozturk/bylaw/main/docs/images/screenshot-inline-light.png" alt="A critical SQL injection finding citing CONTRIBUTING.md line 3, with a suggested change" width="600">
</picture>

The summary checks the change against the acceptance criteria of the issue it closes:

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/tunahanaliozturk/bylaw/main/docs/images/screenshot-summary-dark.png">
  <img src="https://raw.githubusercontent.com/tunahanaliozturk/bylaw/main/docs/images/screenshot-summary-light.png" alt="The bylaw summary with a requirements table: one criterion partly met, two missing" width="600">
</picture>

## Quick start

**GitHub Action.** Add `.github/workflows/bylaw.yml`:

```yaml
name: bylaw
on:
  pull_request:
    types: [opened, synchronize, reopened, ready_for_review]
permissions:
  contents: read
  pull-requests: write
  issues: read
jobs:
  review:
    runs-on: ubuntu-latest
    steps:
      - uses: tunahanaliozturk/bylaw@v0
        with:
          api-key: ${{ secrets.ANTHROPIC_API_KEY }}
```

Without a key it still runs the deterministic checks. OpenAI works too (`provider: openai`, `model: ...`), and so do Amazon Bedrock, Google Vertex AI, Microsoft Foundry, Azure OpenAI and local models through Ollama, vLLM or LM Studio, for teams whose code may not go to a public API: [docs/providers.md](https://github.com/tunahanaliozturk/bylaw/blob/main/docs/providers.md) lists what leaves the machine with each and which variables it reads. Fork pull requests need [the `pull_request_target` recipe](https://github.com/tunahanaliozturk/bylaw/blob/main/docs/recipes/pull-request-target.yml); read the warning at its top first.

**GitHub App, for an organisation.** One install instead of a workflow file per repository: a server you
run receives every chosen repository's pull requests, settings come from the organisation's `.github`
repository, and each installation has its own model key. There is no hosted bylaw; you register the app
from [the manifest](https://github.com/tunahanaliozturk/bylaw/blob/main/docs/app/manifest.json) and run
the container image. Setup: [docs/app/deploy.md](https://github.com/tunahanaliozturk/bylaw/blob/main/docs/app/deploy.md).

**GitLab merge requests.** Copy the job in [docs/recipes/gitlab-ci.yml](https://github.com/tunahanaliozturk/bylaw/blob/main/docs/recipes/gitlab-ci.yml) into your `.gitlab-ci.yml` and add a project access token with the Developer role as the masked variable `GITLAB_TOKEN`; `ANTHROPIC_API_KEY` is optional, as on GitHub. The job token cannot post notes, which is why it needs its own token. Merge requests get the same inline comments, summary and re-run behaviour; what differs, and why, is in [docs/hosts.md](https://github.com/tunahanaliozturk/bylaw/blob/main/docs/hosts.md#gitlab-ci) and [ADR 0020](https://github.com/tunahanaliozturk/bylaw/blob/main/docs/adr/0020-gitlab.md).

**Claude Code or Codex.** The host's own model reviews, so no API key is needed:

```
/plugin marketplace add tunahanaliozturk/bylaw        # Claude Code
/plugin install bylaw@bylaw
codex plugin marketplace add tunahanaliozturk/bylaw   # Codex, then /plugins
```

Then ask "review pull request 12 with bylaw", or run `/bylaw-review 12` in Claude Code. Details: [docs/hosts.md](https://github.com/tunahanaliozturk/bylaw/blob/main/docs/hosts.md).

**Any MCP client.** Claude Desktop, Cursor, VS Code, Codex or Claude Code can call bylaw as an MCP server, again with their own model and no API key:

```
uvx --from "bylaw[mcp]" bylaw mcp --root /path/to/code
```

The tools are read-only unless you add `--allow-post`. Setup for each client: [docs/mcp.md](https://github.com/tunahanaliozturk/bylaw/blob/main/docs/mcp.md).

**On your branch, before the pull request.** Ask Claude Code or Codex to "review this branch with bylaw", or use the CLI with [uv](https://docs.astral.sh/uv/):

```
alias bylaw='uvx bylaw'
bylaw context --base main --output context.json
bylaw review --context context.json   # prints the findings as JSON; set ANTHROPIC_API_KEY for the model review
```

## How it works

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/tunahanaliozturk/bylaw/main/docs/images/flow-dark.png">
  <img src="https://raw.githubusercontent.com/tunahanaliozturk/bylaw/main/docs/images/flow-light.png" alt="Pull request, then context, then deterministic checks and the reviewer, then validation, then comments on the pull request" width="100%">
</picture>

1. **Context.** bylaw reads the diff, the rule files and `.bylaw.toml` from the **base** branch (so a change cannot loosen its own review), and the issues, specs and tracker work items the change links.
2. **Review.** A model reviews with a fixed brief and a strict output schema. Text from the pull request, its issues and specs is treated as data, never as instructions.
3. **Validate.** Every finding must sit on a line the change adds, and every rule citation must point at a real line of a rule that applies to the file, or at a linter rule id the configuration turns on for it. Anything else is dropped before it can be posted.
4. **Post.** Inline comments for findings at or above the threshold, one summary comment with the requirement checklist. State lives in that summary, so the Action needs no server and nothing needs a database.

The design and its trade-offs: [docs/design.md](https://github.com/tunahanaliozturk/bylaw/blob/main/docs/design.md) and the [ADRs](https://github.com/tunahanaliozturk/bylaw/tree/main/docs/adr/).

## Configuration

Optional `.bylaw.toml` at the repository root, always read from the base branch:

```toml
severity_threshold = "medium"   # inline comments at or above this; the rest go in the summary
max_comments = 15               # inline comments per run, 0 to 50
spec_globs = ["docs/specs/**", "**/REQUIREMENTS.md"]
adr_globs = ["docs/adr/**", "doc/adr/**", "docs/decisions/**"]  # accepted ADRs here are decisions a change is held to
issue_repos = []                # other repositories whose issues may be quoted, e.g. ["acme/roadmap"]
input_token_budget = 300000     # model input in tokens; the largest files are left out first
incremental = true              # on a new push, send the model only the files whose change differs

[budget]
pr_tokens = 500000              # optional: model tokens one pull request may use across all runs

[jira]                          # optional: Jira issues a pull request names, such as PROJ-123
url = "https://acme.atlassian.net"
projects = ["PROJ"]
```

Rule files need no setting. bylaw reads them from the base branch: the ones at the root and, in a monorepo, the nearest `AGENTS.md`, `CLAUDE.md`, `CONTRIBUTING.md` and linter configuration above each changed file, plus every `.editorconfig` on the way up as EditorConfig itself does, so `packages/api/` is reviewed against its own rules and the root ones. From Ruff (following `extend`), ESLint (`.eslintrc.json` or `.eslintrc.yml`), golangci-lint and .NET analyzer settings it also reads which rule ids are on, and findings can cite them as `ruff:S608`. A cited id is dropped when the configuration turns it off, or does not turn it on and bylaw read all of it; an id that may come from an ESLint `extends` or a .NET analysis level is kept. ESLint configs written in JavaScript are never run; they stay text.

ADRs are read from the base branch too, from `adr_globs`, subdirectories included. bylaw keeps the accepted ones, whether the status is a `Status: Accepted` line, a `## Status` section (Nygard, adr-tools), a table row or MADR front matter, and shows the reviewer only each one's title, status and decision section, newest first, about 4,000 tokens at most; the summary notes what was cut or left out, and names any ADR it could not read. Superseded, deprecated, rejected and proposed ADRs are left out. An ADR under a package, such as `packages/api/docs/adr/`, applies only to that package. A finding may cite only a decision line the reviewer was shown.

Requirements can also come from Jira, Azure Boards (`AB#123`) and Linear. Each is an opt-in with an allow list and a token in the environment; setup, and `quote_trackers = false` for private trackers, are in [docs/trackers.md](https://github.com/tunahanaliozturk/bylaw/blob/main/docs/trackers.md).

## Evaluation

bylaw is measured on 57 labelled pull requests in Python, TypeScript, Go and C#: planted security problems, bugs, rule breaks, missed acceptance criteria, scope creep, and clean changes, five of them in a monorepo whose packages have conflicting rules and two next to accepted, superseded and proposed ADRs. Results are per model and date: [docs/eval/README.md](https://github.com/tunahanaliozturk/bylaw/blob/main/docs/eval/README.md).

Runs from 16 October 2026, on the 50 cases the set had then: the GitHub Action calling the API, and Claude Code and Codex reviewing as hosts with no API key ([API](https://github.com/tunahanaliozturk/bylaw/blob/main/eval/results/2026-10-16-opus-5-5/report.md), [Claude Code](https://github.com/tunahanaliozturk/bylaw/blob/main/eval/results/2026-10-16-claude-code-host/report.md), [Codex](https://github.com/tunahanaliozturk/bylaw/blob/main/eval/results/2026-10-16-codex-host/report.md)):

| | Action, `claude-opus-5-5` | Claude Code host | Codex host, `gpt-6-sol` |
| --- | --- | --- | --- |
| Planted security problems found | 10 of 10 | 10 of 10 | 10 of 10 |
| Planted bugs found | 10 of 10 | 10 of 10 | 10 of 10 |
| Rule breaks found | 10 of 10 | 10 of 10 | 10 of 10 |
| Rule citations on the right line | 8 of 8 | 8 of 8 | 8 of 8 |
| Acceptance criteria judged correctly | 21 of 21 | 21 of 21 | 21 of 21 |
| Scope creep found | 4 of 4 | 4 of 4 | 4 of 4 |
| Clean pull requests with an inline comment | 1 of 9 | 0 of 9 | 1 of 9 |
| Model findings dropped by validation | 1 of 74 | 0 of 53 | 0 of 56 |
| Median review time, cost per review | 6.5 s, about $0.03 | no API cost | no API cost |

Both inline comments on clean changes are the same remark on the same case (`py-clean-contained-path`): the upload path is compared after resolving one side only. Host runs saw the briefs under neutral names, so case names could not hint at the answers.

The Action's run for v0.5 on 19 October 2026, on 57 planted cases, found all 35 planted defects, cited the right rule in 11 of 11 rule findings, judged all 21 criteria correctly and left an inline comment on 1 of 11 clean pull requests ([report](https://github.com/tunahanaliozturk/bylaw/blob/main/eval/results/2026-10-19-opus-5-5-v0.5/report.md)). The same model through the `openai-compatible` provider, which asks for JSON and validates it instead of using the API's structured output, scored the same ([report](https://github.com/tunahanaliozturk/bylaw/blob/main/eval/results/2026-10-19-openai-compatible-opus-5-5/report.md)). The v0.2 run the same day had inline comments on 2 of 9 clean pull requests ([report](https://github.com/tunahanaliozturk/bylaw/blob/main/eval/results/2026-10-18-opus-5-5/report.md)); the same model varies from run to run, so read single runs with that in mind.

These are small, planted changes; real pull requests are larger and messier ([ADR 0010](https://github.com/tunahanaliozturk/bylaw/blob/main/docs/adr/0010-evaluation-on-planted-cases.md)), so treat the numbers as an upper bound on what the model catches. A second set of 25 real pull requests from permissively licensed projects is frozen in `eval/real/` and reported apart ([ADR 0015](https://github.com/tunahanaliozturk/bylaw/blob/main/docs/adr/0015-real-pull-request-set.md)); its labels are a first draft until two people have checked them, so it has no numbers to quote yet.

## Costs

A review is one model call. On the evaluation above it used about 3,900 input and 520 output tokens per pull request, about $0.03 at Claude Opus 5.5 prices; a large pull request costs more, up to the input budget (`input_token_budget`, 300,000 tokens by default). On a new push only the files whose change differs from the last run go to the model; the rest keep their earlier findings ([ADR 0012](https://github.com/tunahanaliozturk/bylaw/blob/main/docs/adr/0012-incremental-review.md)). The summary's footer shows the tokens of the run and of the pull request, and `[budget] pr_tokens` stops the model review on a pull request that has used its share; the cap is approximate, because output tokens and cancelled runs are not cut to it. To cap spending across pull requests, set a monthly limit for the key or workspace in the provider's console; bylaw cannot see your balance.

## Contributing and security

Contributions are welcome: [CONTRIBUTING.md](https://github.com/tunahanaliozturk/bylaw/blob/main/CONTRIBUTING.md). Please report vulnerabilities privately as described in [SECURITY.md](https://github.com/tunahanaliozturk/bylaw/blob/main/SECURITY.md), not in a public issue.
bylaw collects no data; the GitHub App is a server you run yourself. What it sends where is in [docs/privacy.md](https://github.com/tunahanaliozturk/bylaw/blob/main/docs/privacy.md), and per model provider in [docs/providers.md](https://github.com/tunahanaliozturk/bylaw/blob/main/docs/providers.md).

## Licence

[MIT](https://github.com/tunahanaliozturk/bylaw/blob/main/LICENSE)
