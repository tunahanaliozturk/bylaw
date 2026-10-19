# Running bylaw

bylaw runs in three places. They share the same checks and comment format; they differ in who does the reviewing.

## GitHub Action

The Action calls a model with your own key. Copy `docs/recipes/pull-request.yml` into `.github/workflows/bylaw.yml` and add the key as the repository secret `ANTHROPIC_API_KEY`. Without a key it still runs the deterministic checks. Fork pull requests need `docs/recipes/pull-request-target.yml`; read the warning at its top first.

## GitLab CI

bylaw reviews GitLab merge requests the same way: inline discussions on the changed lines and one summary note, edited on every run. Copy the `bylaw` job from `docs/recipes/gitlab-ci.yml` into your `.gitlab-ci.yml` and add two masked CI/CD variables:

- `GITLAB_TOKEN`: a project access token with the Developer role and the `api` scope. bylaw posts as its bot user. The job token (`CI_JOB_TOKEN`) cannot read a merge request's diff or post a note, so it is not enough. Leave "Protect variable" off unless your setup lets it through: since GitLab 18.1 a protected variable reaches a merge request pipeline only when a Maintainer allows it and both branches are protected and in the same project ([Control access to protected variables](https://docs.gitlab.com/ci/pipelines/merge_request_pipelines/#control-access-to-protected-variables-and-runners)). Feature branches usually are not protected, and a fork's pipeline never gets one.

The job sets `GIT_STRATEGY: none`. bylaw reads the change, the rules and the issues through the API, so there is nothing to check out, and the merge request's files never land in the job's directory.
- `ANTHROPIC_API_KEY`, optional, for the model review.

Comments from Developers, Maintainers and Owners count as trusted, the GitLab peer of GitHub's write access: their `bylaw: ignore` mutes a finding, and their issue comments join the requirements. Internal notes and confidential issues are never quoted. Details and trade-offs: [ADR 0020](adr/0020-gitlab.md).

To run it from a terminal: `GITLAB_TOKEN=... uvx bylaw review --gitlab-mr 12 --project group/app`, with `CI_API_V4_URL` set for a self-managed instance (the default is `https://gitlab.com/api/v4`). Add `--post` to publish.

### Merge requests from forks

A merge request from a fork runs its pipeline in the fork, with the fork's variables, so bylaw has no token there; it prints a note and exits with success. A project member who can run pipelines can run it in the parent project instead, from the merge request's Pipelines tab (see [Run pipelines in the parent project](https://docs.gitlab.com/ci/pipelines/merge_request_pipelines/#run-pipelines-in-the-parent-project)). That pipeline gets the parent's variables, the token included, and its job definition comes from the fork's branch. bylaw itself never runs the merge request's code, but the fork's `.gitlab-ci.yml` or a script it calls could print the token. Read the change to those files before you start it, and rotate the token if you ever ran one you had not read.

## Claude Code

Claude itself reviews, so no extra key is needed.

```
/plugin marketplace add tunahanaliozturk/bylaw
/plugin install bylaw@bylaw
```

Then ask for a review ("review this branch with bylaw") or run `/bylaw-review 12` for pull request 12, or `/bylaw-review 12 post` to post the review to it.

## Codex

The Codex model reviews, so no extra key is needed.

```
codex plugin marketplace add tunahanaliozturk/bylaw
```

Then open `/plugins` in Codex, install `bylaw`, and start a new session. Ask "review pull request 12 with bylaw".

To use only the skill without the plugin, copy `plugin/skills/bylaw-review` into `~/.agents/skills/` (all your projects) or into `.agents/skills/` in one repository. The skill runs the released version from PyPI that it names.

## What every host needs

- [uv](https://docs.astral.sh/uv/getting-started/installation/), which runs bylaw without a separate install.
- For pull requests, a GitHub token: `GITHUB_TOKEN`, `GH_TOKEN`, or a logged-in GitHub CLI.
- For GitLab merge requests, a project access token in `GITLAB_TOKEN`.
