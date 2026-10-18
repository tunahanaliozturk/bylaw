# Privacy

bylaw is a command-line tool, a GitHub Action and a self-hosted GitHub App that run in your environment: your terminal, your Claude Code or Codex session, your GitHub Actions runner, or a server you run. bylaw's authors run no server for it and collect nothing. There is no telemetry.

What leaves your machine or runner, and where it goes:

- **GitHub.** bylaw reads the pull request, its files, the linked issues and their comments through the GitHub API with the token you give it, and writes review comments when you ask it to post.
- **Your work item tracker, if you configure one.** With a `[jira]`, `[azure_boards]` or `[linear]` table in `.bylaw.toml`, bylaw reads the work items a pull request names from that tracker, with the token you put in the environment ([trackers.md](trackers.md)). Their text joins the requirement text below, and the summary comment quotes their criteria unless `quote_trackers = false`.
- **The model provider you choose.** With an API key (the Action, `bylaw review`), the pull request title, the diff with its file paths, the rule files, the decision sections of accepted ADRs and the requirement text go to that provider (Anthropic or OpenAI) under your account and its terms. bylaw asks OpenAI not to store the response (`store: false`). With Claude Code or Codex, the host's own model reads them as part of your session.
- **Nothing else.** bylaw sends no data to its authors or to any third party.

- **The GitHub App, if you run it.** GitHub sends pull request events to your server, which reads and writes through the API with tokens it mints for itself and sends to the model provider what the Action sends. It keeps no database: its queue and the list of heads it reviewed live in memory and are gone on restart ([ADR 0017](adr/0017-github-app.md)).

Keys and tokens are read from the environment or, for the app, from files you mount, never written to files, logs or comments.

Questions or concerns: open an issue, or for anything sensitive use the private report described in [SECURITY.md](../SECURITY.md).
