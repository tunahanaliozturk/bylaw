# Privacy

bylaw is a command-line tool and a GitHub Action that runs in your environment: your terminal, your Claude Code or Codex session, or your GitHub Actions runner. It has no server and collects nothing. There is no telemetry.

What leaves your machine or runner, and where it goes:

- **GitHub.** bylaw reads the pull request, its files, the linked issues and their comments through the GitHub API with the token you give it, and writes review comments when you ask it to post.
- **Your work item tracker, if you configure one.** With a `[jira]`, `[azure_boards]` or `[linear]` table in `.bylaw.toml`, bylaw reads the work items a pull request names from that tracker, with the token you put in the environment ([trackers.md](trackers.md)). Their text joins the requirement text below, and the summary comment quotes their criteria unless `quote_trackers = false`.
- **The model provider you choose.** For the model review (the Action, `bylaw review`), the pull request title, the diff with its file paths, the rule files, the decision sections of accepted ADRs and the requirement text go to that provider under your account and its terms: Anthropic, OpenAI, your Amazon Bedrock, Vertex AI, Microsoft Foundry or Azure OpenAI resource, or the local server you name with `--base-url`, where on `localhost` nothing leaves the machine. [providers.md](providers.md) has the table, with where each one sends the data and which variables it reads. bylaw asks OpenAI and Azure OpenAI not to store the response (`store: false`). With Claude Code or Codex, the host's own model reads them as part of your session.
- **Nothing else.** bylaw sends no data to its authors or to any third party.

Keys and tokens are read from the environment, or from a cloud's own credential chain, never written to files, logs or comments. A key meant for one provider is never sent to another.

Questions or concerns: open an issue, or for anything sensitive use the private report described in [SECURITY.md](../SECURITY.md).
