# Security review for 1.0

- **Date:** 19 October 2026
- **Commit reviewed:** `b4f50a1` on `main`, the state after the 0.6.0 release and the learning work
- **Scope:** the whole tool, as [SECURITY.md](../SECURITY.md) defines it: the GitHub Action and its
  recipes, the CLI, local reviews, the GitHub App, the MCP server, GitLab, the trackers, model providers,
  rendering, learning, the HTML report and the supply chain
- **Result:** no critical or high finding; one medium, one low to medium, five low and three
  informational, all fixed for 1.0

## Method

The review read the source and the documentation against one question per trust boundary: what can the
person on the far side of it make bylaw do? The far sides were a pull request's author (including an
organisation member with read access only), a fork, an issue or work item author, a repository inside an
organisation running the GitHub App, a repository handed to `bylaw mcp`, the model's answer, and anyone
who can reach the App's webhook. For each finding the fix was written test first: a regression test that
failed for the reason given below, then the change, with the gates green after each commit (`uv sync
--locked`, Ruff, mypy in strict mode, the unit and integration tests, the licence audit, and the
evaluation without a model).

No model was called and no key was used.

## Findings

Commit ids are those on the `v1.0-security` branch; a rebase merge gives them new ids, and the subject
lines stay the same.

### 1. Medium: a pull request's author could hide a finding and plant the summary

**What.** ADR 0008 trusts comments by bots and by authors with the `OWNER`, `MEMBER` or `COLLABORATOR`
association. GitHub gives `MEMBER` to every member of an organisation, including those with read access
only. Such a member opening a pull request could start a review thread whose first comment carried the
fingerprint marker of a finding bylaw was about to post. bylaw took the thread for its own and posted no
inline comment, and because the summary did not list findings in open threads, the finding was shown
nowhere. The same author could post an issue comment opening with `<!-- bylaw:summary -->`: with no bot
summary yet, bylaw used it as its summary, edited a person's comment, and read its `auto_resolved` list,
so planted thread ids made bylaw reopen threads. Review memory and outcomes were already read only from a
bot's summary.

**Fix.** A fingerprint counts only in a first comment by a trusted author who is not the pull request's
author, unless that author is bylaw's own account (a trusted bot, a personal token's owner on GitHub, the
token's user on GitLab), both in a run and in the outcomes recorded at close. On GitHub the summary is a
trusted bot's comment or, with a personal token, the token owner's (learnt from `GET /user`, asked only
when no bot summary exists); a person's comment is never edited. GitLab already required its own account
when it knows it; the fallback for a token that cannot say who it is now skips the merge request author.
The summary lists findings in open threads under "Open in a review thread". ADR 0008 has a dated
amendment.

**Tests.** `test_a_fingerprint_the_pull_request_author_planted_is_ignored_even_from_a_member`,
`test_a_planted_summary_is_left_alone_and_bylaw_posts_its_own`,
`test_a_persons_marker_comment_is_never_the_summary_with_a_workflow_token`,
`test_at_close_a_marker_the_pull_request_author_planted_changes_nothing`,
`test_a_marker_the_merge_request_author_planted_is_not_bylaws_own`,
`test_findings_in_open_threads_are_listed_so_none_is_shown_nowhere`, and tests that bylaw's own account
still counts on a pull request it opened.

**Status.** Fixed in `cff4ad9`.

### 2. Low to medium: the fork recipe let a fork author spend past the token budget

**What.** `docs/recipes/pull-request-target.yml` runs on `synchronize` while the `bylaw` label is on, with
`cancel-in-progress: true`. A fork author could push again and again: each push cancelled the run before
it, after its model call but before its tokens reached the summary, so `[budget] pr_tokens` never moved.

**Fix.** The recipe sets `cancel-in-progress: false`, explains why, and shows `[budget] pr_tokens` in its
header. ADR 0006 has a dated amendment.

**Test.** `test_the_fork_recipe_never_cancels_a_review_in_progress`; the existing recipe tests still pass.

**Status.** Fixed in `3faf044`.

### 3. Low: reference notes linked and cross-referenced other repositories' issues

**What.** Notes such as "victim-org/project#1 is in another repository" and "Could not read ..." wrote
the label as plain text, which GitHub and GitLab turn into a link and a cross-reference on that issue. A
pull request body with 300 references made 300 notes and 300 cross-references.

**Fix.** Labels in these notes sit in code spans, and each kind of note lists at most five references
followed by one line with the count of the rest.

**Tests.** `test_hundreds_of_references_to_other_repositories_make_a_few_notes_in_code_spans`,
`test_hundreds_of_unreadable_references_make_a_few_notes`.

**Status.** Fixed in `985168c`.

### 4. Low: one oversized finding stopped the whole review

**What.** A finding's message, suggestion and evidence had no length limit. GitHub refuses a review when
one comment is over 65,536 characters, so a single oversized finding meant nothing was posted.

**Fix.** Validation cuts a message over 2,000 characters to that length, ending in `...`, and leaves out
a suggestion over 10,000 characters, keeping the finding in both cases and noting what it did. Dropping
the finding instead, as the first fix did, would have made a finding posted on an earlier run read as
fixed and resolved its thread. A finding whose evidence is over 500 characters is still dropped: evidence
names a rule or a criterion, so a long one cites nothing. The system prompt states both limits. At those
limits, with the worst escaping, an inline comment stays well under GitHub's limit and far under GitLab's
million-character notes; the summary was already trimmed to fit.

**Tests.** `test_an_oversized_finding_is_cut_down_rather_than_dropped`,
`test_a_finding_at_every_limit_fits_one_github_comment_and_one_gitlab_note`,
`test_the_system_prompt_states_the_size_limits_validation_applies`.

**Status.** Fixed in `123138f`, and changed from dropping to cutting in review of the fix.

### 5. Low: local reviews ran the repository's git textconv drivers

**What.** A local review, including one through `bylaw mcp`, ran `git diff` without `--no-textconv`, so a
`diff.<driver>.textconv` in the repository's config ran for files its `.gitattributes` named.

**Fix.** `git diff` and `git show` pass `--no-textconv` (`git diff` already passed `--no-ext-diff`),
`git log` passes `--no-show-signature` so `log.showSignature` cannot start a `gpg.program`, and every git
command runs with `-c core.fsmonitor=false`. `docs/mcp.md` says so.

**Test.** `test_a_textconv_driver_in_the_repository_config_never_runs`, with a driver that writes a
marker file outside the repository.

**Status.** Fixed in `a14beae`.

### 6. Low: the learning recipe gave the review job `contents: write`

**What.** `docs/learning.md` showed one job with `contents: write` for both the review and the step that
records outcomes. The review reads the author's text and sends it to a model, so it should not be able to
push.

**Fix.** Two jobs: `review` with `contents: read`, and `learn`, which runs only when
`github.event.action == 'closed'`, with `contents: write`.

**Test.** `test_the_learning_recipe_gives_write_access_to_contents_only_to_the_closing_job`.

**Status.** Fixed in `e1fcd04`.

### 7. Low: supply chain pins

**What.** The GitLab recipe used the uv image by a moving tag, and `uvx bylaw@X` pins bylaw but resolves
its dependencies afresh on every run. The documentation pinned the Action by tag only.

**Fix.** The GitLab recipe pins the uv image by digest, with the command that reads the current one, and
sets `UV_EXCLUDE_NEWER` so dependencies published after the pinned release never reach the job;
`docs/hosts.md` describes a hashed requirements file as the stricter option. The README, the recipes and
SECURITY.md recommend pinning the Action by commit SHA, with `@v0` and later `@v1` as the convenient
choice, and SECURITY.md says the `v*` tags are protected by a ruleset.

**Test.** `test_the_gitlab_recipe_pins_its_image_by_digest_and_its_dependencies_by_date`.

**Status.** Fixed in `c6312e8`. The tag ruleset is a repository setting for a maintainer to apply.

### 8. Informational: the release build was not reproducible

**What.** `uv build` in `release.yml` took whatever hatchling was newest at release time.

**Fix.** `tools/build-constraints.txt` pins hatchling and its dependencies with hashes, and the release
runs `uv build --build-constraints tools/build-constraints.txt --require-hashes`. The flag was checked in
uv 0.13.1; two builds of one commit gave the same wheel and sdist bytes, and a wrong hash stopped the
build.

**Test.** `test_releases_are_built_with_the_hashed_build_backend`.

**Status.** Fixed in `c6312e8`.

### 9. Informational: long suggestion fences on older GitLab

**What.** A suggestion that holds three backticks in a row gets a longer fence. An older GitLab whose
quick action extractor knows only three-backtick fences would read a line in it that starts with `/` as
a quick action.

**Fix.** Such a suggestion, when it also has a line starting with `/`, is left out of the GitLab note with
a short explanation. ADR 0020 says so.

**Test.** `test_a_suggestion_that_needs_a_long_fence_and_has_a_slash_line_is_left_out`.

**Status.** Fixed in `9440331`.

### 10. Informational: organisation defaults could be raised by any repository

**What.** In the GitHub App, a repository's `.bylaw.toml` could set `[app] model_review = "all"` or a
larger `[budget] pr_tokens` over the organisation's defaults, spending the installation's key on every
fork pull request.

**Fix.** A `[ceiling]` table, read only from the organisation's `.bylaw.toml`, caps `model_review` and
`pr_tokens` for every repository. Under a `"trusted"` ceiling, `model_review_label` comes from the
organisation's file only, since a repository could name a label an auto-labeller adds to every pull
request. With no repository budget the app uses the smaller of its 500,000 default and the ceiling. A
repository's own `[ceiling]` is ignored. ADR 0017 and the deploy guide document it.

**Tests.** `test_a_repository_cannot_raise_the_organisations_ceiling`,
`test_under_a_trusted_ceiling_only_the_organisation_names_the_review_label`,
`test_the_app_budget_with_a_ceiling_and_no_repository_cap_is_the_smaller_of_the_two`,
`test_a_repositorys_own_ceiling_can_neither_lift_nor_replace_the_organisations`,
`test_under_a_trusted_ceiling_the_gate_does_not_suggest_opening_the_review_to_all`.

**Status.** Fixed in `782f0ea`; the label and the default budget were closed in review of the fix.

## Checked and found sound

- **The Action.** Inputs reach scripts through environment variables, never through expression
  expansion in `run:`. Third-party actions are pinned by commit. bylaw installs with `uv sync --locked
  --no-dev` from the Action's own source and never checks out the pull request. A `pull_request` run that
  gets no secrets (a fork, a deleted fork or Dependabot) is recognised (`_without_secrets`) and ends with a
  notice instead of failing on a read-only token. The `pull_request_target` recipe is label gated.
  Working files live at fixed paths under `RUNNER_TEMP`. Pages deploys only from a run without a pull
  request. Log lines built from untrusted text are flattened, so they cannot start a workflow command.
- **The CLI.** Arguments are parsed with `argparse`; output goes to paths the user names. Snapshot paths
  are checked to stay inside their directory. `--base` refuses a value starting with `-`. git never reads
  standard input (`stdin=DEVNULL`). Tracker sites are pinned when the repository is not the run's own.
- **Rules and configuration** are read from the base SHA, and the organisation's defaults from the
  `.github` repository's default branch.
- **The GitHub App.** The webhook's HMAC is checked on the raw bytes before parsing; body sizes are
  capped. Installation tokens are scoped to the repository and the permissions a review needs, and the
  repository is checked against GitHub's answer. The token that reads defaults is read-only. The server
  binds to 127.0.0.1 by default and its image runs as a non-root user and is pinned by digest. Secrets
  are never logged. The model gate keeps fork and outside pull requests off the key by default; each
  installation uses its own provider key, with a default token budget. Trust in its own comments is by
  the App's bot login. Queues are bounded per installation.
- **The MCP server.** Local paths must be inside the roots, and so must the work tree, the git directory
  and the common git directory. `post` is listed only with `--allow-post` and checks the head again
  before posting, with `.bylaw.toml` from the base. Tracker sites are pinned by the server's environment.
- **GitLab.** Carriage returns are removed before quick actions are neutralised. Trust is Developer or
  higher. The summary and memory are bylaw's own account's notes. Confidential issues are skipped. Fork
  pipelines get no token, and bylaw exits cleanly there.
- **Trackers.** Tokens come only from the environment. Allow lists are checked on the reference and on
  the answer. Requests follow no redirects, so credentials never travel to another host, and sites must
  be HTTPS. At most 10 work items are read. A work item is read only for a trusted author. One note
  covers "does not exist" and "outside the allow list", so it is no existence oracle. `quote_trackers =
  false` keeps work item text out of the summary.
- **Model providers.** Keys are routed per provider, and an explicit key wins. A `--base-url` must use
  https unless the server is on the same machine. A custom header list set for one provider's SDK, which
  can carry an `Authorization` line, is refused when another provider is used. Provider errors are
  sanitised before they reach a log or comment. OpenAI-compatible requests ask for `store=false`.
- **Rendering.** Every string bylaw did not write is escaped; mentions get a zero-width space; state is
  escaped so model text cannot close its comment; the state block is the last thing in the summary and
  the fingerprint marker the last thing in an inline comment; suggestion fences are longer than any
  backtick run inside; data blocks in the brief use a random nonce.
- **Memory, outcomes and learning.** Memory and outcomes come only from a bot's summary; a mute needs a
  trusted author who is not the pull request's; a dismissal by the author never counts towards a
  suggestion; a security finding is never suggested or suppressed.
- **The HTML report** escapes every value, and the evidence file holds only what the summary already
  shows.
- **Supply chain.** `actions/checkout` runs with `persist-credentials: false`; CI tokens are read-only;
  dependencies install with `uv sync --locked`; the licence audit, CodeQL and Dependabot run; CODEOWNERS
  covers the repository; PyPI uploads use trusted publishing behind an environment that needs a
  maintainer's approval.

## Left for later

- A pull request body can still name many references in its own repository; each is read through the
  API once. The notes are capped, the reads are not. GitHub's rate limit bounds the cost.
