# Security policy

## Reporting a vulnerability

Report it privately through GitHub: the **Security** tab of this repository, then **Report a vulnerability**. Please do not open a public issue, discussion or pull request for it.

Include what you found, how to reproduce it, and what an attacker gains. You will get an answer within 7 days, and a fix or a plan within 30 days for confirmed issues. You are credited in the advisory unless you ask not to be.

## Supported versions

Security fixes go into the latest release only.

## What counts

bylaw runs on untrusted input (pull request diffs, titles, issues and specs) with a write token and often a model API key. These are in scope:

- Text in a pull request, issue or spec that makes bylaw post, approve, hide findings or leak data (prompt injection that gets past validation).
- A model API key or GitHub token reaching a log, a comment or an error message.
- A way for a pull request to change the rules or `.bylaw.toml` used to review it.
- Code execution through the Action, including through the `pull_request_target` recipe used as documented.

Out of scope: a model missing a finding or making a wrong one (that is a quality issue, please open a normal issue), and workflows that ignore the warnings in `docs/recipes/`.

## How bylaw protects itself

- Rules and configuration are read from the base branch ([ADR 0004](docs/adr/0004-rules-from-base-branch.md)).
- Repository text reaches the model inside randomly tagged data blocks, and the brief says to treat it as data.
- Every finding is validated before posting: it must sit on a line the change adds and cite a line that exists.
- Only trusted authors' comments carry state; a pull request author cannot mute a finding ([ADR 0008](docs/adr/0008-trusted-authors-carry-state.md)).
- The Action pins its dependencies by commit and lock file, and errors never include keys.
