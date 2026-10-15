# Running bylaw

bylaw runs in three places. They share the same checks and comment format; they differ in who does the reviewing.

## GitHub Action

The Action calls a model with your own key. Copy `docs/recipes/pull-request.yml` into `.github/workflows/bylaw.yml` and add the key as the repository secret `ANTHROPIC_API_KEY`. Without a key it still runs the deterministic checks. Fork pull requests need `docs/recipes/pull-request-target.yml`; read the warning at its top first.

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

To use only the skill without the plugin, copy `skills/bylaw-review` into `~/.agents/skills/` (all your projects) or into `.agents/skills/` in one repository.

## What every host needs

- [uv](https://docs.astral.sh/uv/getting-started/installation/), which runs bylaw without a separate install.
- For pull requests, a GitHub token: `GITHUB_TOKEN`, `GH_TOKEN`, or a logged-in GitHub CLI.
