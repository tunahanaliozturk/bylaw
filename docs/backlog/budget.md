# Spending limits

Roadmap: Q1 in [ROADMAP.md](../ROADMAP.md). Target: v0.2. Item ids: `BUD-n`.

A team with a fixed amount of API credit needs to know what bylaw costs and to stop it before it overspends. The hard limit for an account belongs in the provider's console (Anthropic and OpenAI both have spend limits per workspace or key), because only the provider knows the balance. bylaw adds limits it can enforce itself, without a server.

**Done when** a repository can cap how many tokens a single pull request may use, every summary says what its review cost, and the docs say where the account-wide limit is set.

## Items

- [x] **BUD-1** (S) `bylaw eval run --max-cost` with given prices stops starting new cases at the limit. Done when: tested, documented in docs/eval/README.md.
- [ ] **BUD-2** (S) README section "Costs": a measured cost per review from the evaluation, and how to set a spend limit in the Anthropic and OpenAI consoles. Done when: numbers come from a committed run.
- [ ] **BUD-3** (M) Per pull request token cap in `.bylaw.toml` (`[budget] pr_tokens`), counted in the summary state; once reached, bylaw's own checks still run and the model review is skipped with a note. Done when: state round trip and skip tests.
- [ ] **BUD-4** (S) The summary's footer gives the tokens this run used and the running total for the pull request. Done when: render test.
- [ ] **BUD-5** (M) A monthly cap per repository. Needs a store across pull requests, so it waits for the outcome store in [learning](learning.md). Done when: ADR on the store.

## Notes

Prices are never stored in the code: they change, and a wrong built-in price is worse than none. Token caps need no prices; USD limits take prices from the user.
