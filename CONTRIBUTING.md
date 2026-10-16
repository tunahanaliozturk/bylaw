# Contributing

Thanks for helping. Bug reports, rule sources bylaw should read, evaluation cases and fixes are all welcome.

Looking for something to do? The [backlog](docs/backlog/README.md) lists every planned item with an id and what done means; the [hardening](docs/backlog/hardening.md) items are a good start.

## Set up

You need [uv](https://docs.astral.sh/uv/) and git.

```
git clone https://github.com/tunahanaliozturk/bylaw
cd bylaw
uv sync
uv run pytest -q
```

## Before you open a pull request

CI runs these; run them locally first:

```
uv run ruff check .
uv run ruff format --check .
uv run mypy src tests
uv run pytest -q
uv run python tools/license_audit.py
```

- One change per pull request, with a test that fails without it. Name tests after the behaviour (`a_rerun_never_repeats_a_comment`), not the function.
- No new dependency unless there is no reasonable way without it. Every dependency must have a permissive licence; the audit enforces that.
- A decision that is hard to reverse gets an ADR in `docs/adr/`.
- Tests never call a model or the live GitHub API.
- Commit messages follow [Conventional Commits](https://www.conventionalcommits.org/) (`feat:`, `fix:`, `docs:`).

## Docs

English with British spelling, short sentences, no em dashes. Say why, not only what.

## Evaluation cases

A new case goes in `eval/cases/<id>/`: the changed files under `head/` and the labels in `case.toml` ([docs/eval/README.md](docs/eval/README.md)). `tests/integration/test_eval_set.py` must stay green; it fails when a label points at a line the change does not add.

## Security

Do not open a public issue for a vulnerability. See [SECURITY.md](SECURITY.md).

By contributing you agree to follow the [code of conduct](CODE_OF_CONDUCT.md) and that your contribution is licensed under the [MIT licence](LICENSE).
