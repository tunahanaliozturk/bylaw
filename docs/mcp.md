# bylaw as an MCP server

`bylaw mcp` offers bylaw's review flow as tools to any agent that speaks the [Model Context
Protocol](https://modelcontextprotocol.io). The agent's own model does the reviewing, as it does in the
Claude Code and Codex plugin, so no model API key is needed. Unlike the plugin, the agent does not need a
shell: it calls tools and gets JSON or text back. The design and its trade-offs are in
[ADR 0019](adr/0019-mcp-server.md).

## What the server offers

| Tool | What it does | Writes anything |
| --- | --- | --- |
| `brief` | What a reviewer reads: bylaw's instructions, then the diff, rules, decisions and requirements. Start here. | no |
| `schema` | The JSON schema a review result must follow. | no |
| `validate` | Drops the findings the context cannot back up, and says why. | no |
| `preview` | The Markdown bylaw would post for a result. | no |
| `context` | The raw review context as JSON, for agents that want the data rather than the brief. | no |
| `post` | Publishes the review to the pull request. Only listed when the server runs with `--allow-post`. | yes |

Each tool takes its target as arguments: `repo` (`owner/name`) and `pr` for a pull request, or `base` (a
branch or ref) and an optional `path` for a local branch. A local review covers committed changes from
`base` to `HEAD`, as `bylaw context --base` does.

`validate`, `preview` and `post` check a result against the context the last `brief` or `context` call
read for the same target. If the pull request gets a new push while the agent is reviewing, its findings
are still checked against the lines it was shown; call `brief` again to review the new push.

`validate` returns the result with bylaw's own deterministic findings, such as `.editorconfig` breaks,
added to the agent's. That result can go straight back into `validate`, `preview` or `post`: bylaw adds
its own findings only when they are missing, so nothing is dropped as a duplicate.

The server tells the agent the order when it connects: brief, review, validate until nothing it meant to
keep is dropped, then preview. So a request such as "review pull request 12 in octo-org/app with bylaw" or
"review this branch against main with bylaw" is enough to start.

## Running it

The server needs [uv](https://docs.astral.sh/uv/getting-started/installation/) and the `mcp` extra:

```
uvx --from "bylaw[mcp]" bylaw mcp
```

The extra is in the first release after 0.5.0. Until then, run it from a clone of this repository with
`uv run --project /path/to/bylaw --extra mcp bylaw mcp`.

The command prints nothing and waits: an MCP client starts it and talks to it over standard input and
output. Options:

- `--root DIR` names a directory whose repositories local reviews may read. Repeat it for more than one.
  Without it, the root is `CLAUDE_PROJECT_DIR` when Claude Code started the server, and otherwise the
  directory the client started it in. That directory differs between clients, so the examples for other
  clients pass `--root` explicitly. A whole drive or `/` is refused as a root, because a client that
  starts the server there would otherwise open every repository on the machine.
- `--allow-post` adds the `post` tool. Leave it out unless you want the agent to be able to comment on
  pull requests; see [Posting](#posting).

For pull requests the server needs `GITHUB_TOKEN` or `GH_TOKEN` in its environment. Without posting, a
fine-grained token with read access to contents, pull requests and issues is enough. The client passes
the token to the server through its configuration; each section below shows how to do that without
writing the token into the file where the client allows it.

## Tracker tokens

Jira and Azure Boards work items need their tokens in the server's environment too ([trackers.md](trackers.md)).
The server also needs to know where those tokens may go. Normally the site comes from the reviewed
repository's `.bylaw.toml`, but here the agent picks the repository, and a pull request can ask it to
review one whose `.bylaw.toml` names someone else's Jira. So the server sends a tracker token only to the
site you pin next to it: `JIRA_URL` (such as `https://acme.atlassian.net`) for Jira and
`AZURE_DEVOPS_ORGANIZATION` for Azure Boards. Without the pin, work items are left out with a note and the
token goes nowhere. Linear has one fixed host and needs no pin.

## Local paths

A local review runs git in the directory the agent names, so the server only accepts directories inside
an allowed root. A relative `path` is read from the first root. The directory must be inside a root, and
so must the repository git finds from it: its work tree, its git directory and, for a worktree, the
repository the worktree belongs to. git looks for a repository in the parent folders too, and a `.git`
file can point anywhere, so a folder in a root could otherwise hand out a repository elsewhere. Symlinks
are followed before the check.

Point the roots at repositories you trust as much as running git in them yourself, because git applies a
repository's own configuration. One thing the check does not follow is alternates: a repository whose
`.git/objects/info/alternates` names another directory reads objects from there too.

## Claude Code

From [Claude Code's MCP documentation](https://code.claude.com/docs/en/mcp): Claude Code's own options,
such as `--env`, go before `--`, and everything after it is the command that starts the server.

```
claude mcp add bylaw --env 'GITHUB_TOKEN=${GITHUB_TOKEN}' -- uvx --from "bylaw[mcp]" bylaw mcp
```

The single quotes keep your shell from expanding the variable, so Claude Code stores it as written and
expands it when it starts the server: the token comes from the environment you start Claude Code in and
never lands in `~/.claude.json`. There is no `--root`: Claude Code sets `CLAUDE_PROJECT_DIR`, the project
it was opened in, in the server's own environment, and bylaw uses it as the root. Writing
`${CLAUDE_PROJECT_DIR}` in the arguments would not work, because Claude Code expands arguments from its
own environment, where that variable is not set.

To share the server with everyone who works on a repository, add it to `.mcp.json` at the project root
instead (`--scope project` writes the same thing):

```json
{
  "mcpServers": {
    "bylaw": {
      "command": "uvx",
      "args": ["--from", "bylaw[mcp]", "bylaw", "mcp"],
      "env": { "GITHUB_TOKEN": "${GITHUB_TOKEN}" }
    }
  }
}
```

Claude Code warns when a tool returns more than 10,000 tokens, and moves a text result to a file that
Claude then reads in parts once it is over 50,000 characters, whatever `MAX_MCP_OUTPUT_TOKENS` says. A
tool can raise that threshold with `anthropic/maxResultSizeChars`, up to 500,000 characters. `brief` does,
because the reviewer has to read all of it, so a brief stays in the conversation up to about 500,000
characters and only a larger one goes to a file. `context` does not: it is raw data an agent rarely
needs whole, and a file is the better place for it. Either way the review works.

## Claude Desktop

Open Settings, then Developer, then Edit Config, and add the server to `claude_desktop_config.json`
(`~/Library/Application Support/Claude/claude_desktop_config.json` on macOS,
`%APPDATA%\Claude\claude_desktop_config.json` on Windows), as [the MCP guide to local
servers](https://modelcontextprotocol.io/docs/develop/connect-local-servers) describes:

```json
{
  "mcpServers": {
    "bylaw": {
      "command": "uvx",
      "args": ["--from", "bylaw[mcp]", "bylaw", "mcp", "--root", "/Users/you/code"],
      "env": { "GITHUB_TOKEN": "github_pat_..." }
    }
  }
}
```

Use absolute paths: the guide asks for them, and Claude Desktop does not start the server in a project
directory. If Claude Desktop cannot find `uvx`, put its full path in `command` (`which uvx` on macOS,
`where uvx` on Windows). Restart Claude Desktop after editing the file.

Claude Desktop documents no variable expansion in this file, so the token is stored in it as plain text.
Use a fine-grained token that can only read, and leave `GITHUB_TOKEN` out entirely if you only review
local branches.

## Codex

From [the Codex MCP documentation](https://developers.openai.com/codex/mcp):

```
codex mcp add bylaw -- uvx --from "bylaw[mcp]" bylaw mcp --root /path/to/code
```

Or edit `~/.codex/config.toml`, or `.codex/config.toml` in a trusted project:

```toml
[mcp_servers.bylaw]
command = "uvx"
args = ["--from", "bylaw[mcp]", "bylaw", "mcp", "--root", "/path/to/code"]
env_vars = ["GITHUB_TOKEN"]
startup_timeout_sec = 60
tool_timeout_sec = 120
```

`env_vars` forwards `GITHUB_TOKEN` from the environment you start Codex in, so the token is not written to
the file. The first start downloads bylaw, which can take longer than Codex's default of 10 seconds, and
reading a large pull request can take longer than its default tool timeout of 60 seconds; hence the two
timeouts. Codex also truncates long tool output; if a large brief is cut, raise its budget with
`[mcp_servers.bylaw.tools.brief]` and `output_token_limit = 100000`.

## Cursor

From [Cursor's MCP documentation](https://cursor.com/docs/context/mcp): add the server to
`.cursor/mcp.json` in a project, or to `~/.cursor/mcp.json` for every project.

```json
{
  "mcpServers": {
    "bylaw": {
      "type": "stdio",
      "command": "uvx",
      "args": ["--from", "bylaw[mcp]", "bylaw", "mcp", "--root", "${workspaceFolder}"],
      "env": { "GITHUB_TOKEN": "${env:GITHUB_TOKEN}" }
    }
  }
}
```

Cursor fills in `${workspaceFolder}` and reads `${env:GITHUB_TOKEN}` from its own environment.

## VS Code

VS Code reads two formats ([configuration
reference](https://code.visualstudio.com/docs/copilot/reference/mcp-configuration), [adding
servers](https://code.visualstudio.com/docs/copilot/customization/mcp-servers)). The portable one is what
VS Code now recommends for new servers, and the one Copilot's agent sessions read directly: `.mcp.json`
at the workspace root, or `$COPILOT_HOME/mcp-config.json` (by default `~/.copilot/mcp-config.json`) for
every workspace. Both hold a `mcpServers` object:

```json
{
  "mcpServers": {
    "bylaw": {
      "type": "stdio",
      "command": "uvx",
      "args": ["--from", "bylaw[mcp]", "bylaw", "mcp", "--root", "/path/to/code"],
      "env": { "GITHUB_TOKEN": "github_pat_..." }
    }
  }
}
```

The portable format supports neither input variables nor environment files, and VS Code documents no
variable expansion for it, so a token in `env` is plain text. Put the server with a token in your user
file, never in the workspace `.mcp.json` that goes into version control, use a fine-grained token that
can only read, and leave `env` out of the workspace file if it only reviews local branches. Use an
absolute `--root`: the workspace `.mcp.json` cannot set the directory the server starts in.

If you want VS Code to prompt for the token and store it securely, the older VS Code format can:
`.vscode/mcp.json` in the workspace, or **MCP: Open User Configuration**. VS Code lists those files as
deprecated, and it does not forward a server that needs `${input:...}` to Copilot's agent sessions, so
this works in VS Code's own chat only:

```json
{
  "inputs": [
    { "type": "promptString", "id": "github-token", "description": "GitHub token for bylaw", "password": true }
  ],
  "servers": {
    "bylaw": {
      "type": "stdio",
      "command": "uvx",
      "args": ["--from", "bylaw[mcp]", "bylaw", "mcp", "--root", "${workspaceFolder}"],
      "env": { "GITHUB_TOKEN": "${input:github-token}" }
    }
  }
}
```

VS Code asks for the token the first time it starts the server and stores it securely, so it is never in
the file, and `${workspaceFolder}` is filled in with the workspace.

## Posting

Posting is off unless you start the server with `--allow-post`; without it the `post` tool is not even
listed, so an agent cannot call it by mistake or because a pull request told it to. With it, `post` takes
`repo`, `pr` and the result, validates the result against the context the brief showed, reads
`.bylaw.toml` from the base branch and publishes the review exactly as `bylaw post --pr` does: inline
comments, the summary comment, and resolving the threads of findings that were fixed. If the pull
request got new commits after the brief, `post` refuses and asks the agent to run `brief` again, so no
comment lands on lines the reviewer never saw.

`post` is marked as not read-only, so clients that ask before running such tools will ask. Codex's
`default_tools_approval_mode = "writes"` does exactly that. Posting needs a token that can write pull
request comments.

Add `--allow-post` after `bylaw mcp` in any of the configurations above:

```
uvx --from "bylaw[mcp]" bylaw mcp --root /path/to/code --allow-post
```

## Troubleshooting

- **The tools do not appear.** Run the command from the configuration in a terminal. It should print
  nothing and wait; press Ctrl+C to stop it. An error there is the error the client saw.
- **"bylaw mcp needs the mcp extra".** The command ran plain `bylaw`; use `uvx --from "bylaw[mcp]" bylaw
  mcp`.
- **"path ... is outside the allowed roots".** The repository is not under a `--root`. Add one, or check
  that the client fills in the variable you used for it.
- **"pull requests need GITHUB_TOKEN or GH_TOKEN".** The client did not pass the token; check the `env`
  part of its configuration and that the variable is set where the client starts.
