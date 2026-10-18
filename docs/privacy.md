# Privacy

bylaw is a command-line tool and a GitHub Action that runs in your environment: your terminal, your Claude Code or Codex session, or your GitHub Actions runner. It has no server and collects nothing. There is no telemetry.

What leaves your machine or runner, and where it goes:

- **GitHub.** bylaw reads the pull request, its files, the linked issues and their comments through the GitHub API with the token you give it, and writes review comments when you ask it to post.
- **Your work item tracker, if you configure one.** With a `[jira]`, `[azure_boards]` or `[linear]` table in `.bylaw.toml`, bylaw reads the work items a pull request names from that tracker, with the token you put in the environment ([trackers.md](trackers.md)). Their text joins the requirement text below, and the summary comment quotes their criteria unless `quote_trackers = false`.
- **The model provider you choose.** With an API key (the Action, `bylaw review`), the pull request title, the diff with its file paths, the rule files and the requirement text go to that provider (Anthropic or OpenAI) under your account and its terms. bylaw asks OpenAI not to store the response (`store: false`). With Claude Code or Codex, the host's own model reads them as part of your session.
- **Nothing else.** bylaw sends no data to its authors or to any third party.

Keys and tokens are read from the environment, never written to files, logs or comments.

Questions or concerns: open an issue, or for anything sensitive use the private report described in [SECURITY.md](../SECURITY.md).
