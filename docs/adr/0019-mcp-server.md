# 0019: An MCP server over the same core, read-only unless posting is allowed

Status: Accepted, 2026-10-18. Builds on 0001.

## Context

Claude Code and Codex review with bylaw through a skill: the host model runs `bylaw context`, `bylaw
prompt`, `bylaw schema`, `bylaw validate` and `bylaw post` as shell commands and passes files between
them. That needs a host that can run shell commands, follow a long skill, and keep a temporary directory
straight. Many agents speak MCP instead: Claude Desktop, Cursor, VS Code and Codex can all call tools on a
local MCP server, and some of them cannot run a shell at all. ADR 0001 kept MCP out of the core and said it
could be added later as a thin wrapper. This is that wrapper.

The risks are the ones any tool server has. The agent that calls the tools may be reading a hostile pull
request, so every argument is untrusted: a path can point anywhere, a base ref can look like a git option,
a repository name goes into GitHub API paths. Publishing comments is the one action with effects other
people see. And tool results go into the agent's context window, which is the scarcest thing it has.

## Decision

- **`bylaw mcp`, over stdio, from an extra.** The server uses the official MCP Python SDK (`mcp` 2.3,
  MIT) and its `MCPServer` class, and runs on standard input and output, which every MCP client
  supports. The SDK sits in an optional extra, `bylaw[mcp]`, so the Action, the CLI and the skill do not
  install it; `bylaw mcp` without it says how to install it. A test checks that importing the CLI does
  not import the SDK.
- **The skill's flow as tools.** `context`, `brief` (what `bylaw prompt` prints), `schema`, `validate`
  and `preview` (what `bylaw post --dry-run` prints, as Markdown). Each tool that needs a target takes it
  as explicit arguments: `repo` and `pr` for a pull request, or `base` and an optional `path` for a local
  branch. Naming both, or neither, is an error. The server's instructions tell the agent the order:
  brief, review, validate until nothing it meant to keep is dropped, preview.
- **Read-only by default.** Every tool carries `readOnlyHint`. The ones that may read GitHub also carry
  `openWorldHint`; `schema` does not.
- **A result is checked against what its brief showed.** The server keeps the context it last read for
  each target. `context` and `brief` always read the target again; `validate` and `preview` use the kept
  context, and read it only when there is none. So a push that lands between the brief and the
  validation cannot move the lines a finding is checked against, and the agent never has to send a large
  context back as an argument. The contexts live as long as the server process.
- **Sizes.** `brief` returns plain text, bounded by `input_token_budget` as it is in the Action, plus a
  second text block naming any file left out for size. `context` returns its JSON once, as text, with no
  output schema: the full ReviewContext schema would sit in every client's tool listing, and structured
  output would send the large JSON twice. The small tools (`schema`, `validate`, `preview`) return
  structured content with an output schema. A result is passed as an object and checked against
  ReviewResult inside the tool rather than in the input schema, so the long result schema is listed once,
  by `schema`.
- **Local paths stay inside allowed roots.** `bylaw mcp --root DIR`, repeatable, names the directories
  local reviews may read; without it, the server's working directory is the only root. A relative `path`
  is resolved against the first root, symlinks followed, and the directory must be inside a root. Then
  `git rev-parse --show-toplevel` must be inside the same root too, because git walks up from a folder,
  and a folder in a root can belong to a repository above it, such as a dotfiles repository in a home
  directory.
- **Arguments are checked where they enter.** A `repo` must look like a GitHub `owner/name` before it goes
  into an API path. A `base` that starts with `-` is refused in `LocalGitSource` itself, so neither the
  server nor the CLI can pass git an option where it expects a ref.
- **Posting is a start-up choice.** `bylaw mcp --allow-post` adds a `post` tool; without the flag the
  tool is not registered at all, so it is neither listed nor callable, and an agent reading a pull request
  that asks it to post cannot. The choice belongs to the person who starts the server, not to the agent
  or the pull request, so it is a flag and not a tool argument. `post` takes `repo`, `pr` and the result,
  validates it against the kept context, reads `.bylaw.toml` from the base branch again, as `bylaw post`
  does, and publishes through the same code. It is marked not read-only, not destructive (it adds
  comments and edits or resolves only bylaw's own) and idempotent (a rerun repeats nothing), so clients
  that ask before a writing tool will ask. With posting on, the server's instructions add that the agent
  posts only when the user asks.
- **No secrets in results.** The GitHub token comes from the server's environment (`GITHUB_TOKEN` or
  `GH_TOKEN`), never from an argument. bylaw's own errors become tool errors with their message, and
  those messages never carry the token (a test sets a sentinel token and checks a failed call); anything
  unexpected is reported by the SDK without its text.

## Consequences

- Any MCP client can run a bylaw review with its own model and no extra API key, without a shell, a
  skill or temporary files.
- The tools are a second public interface next to the CLI. Their names and arguments need the same care
  as the commands the skill depends on.
- Cost: a new optional dependency tree (the SDK brings Starlette, Uvicorn, PyJWT and cryptography among
  others). All of it passes the licence audit; it is installed only with the extra.
- Cost: the kept contexts make the server stateful. A long-lived server that reviews many targets holds
  each one's context in memory until it exits. A session reviews a handful, so there is no eviction.
- Cost: a local review runs git in a directory the user allowed. A repository's own git configuration
  applies, as it does on the command line, so the roots should be repositories the user trusts.
- Clients pass the token through their configuration, and some write it into a config file in plain
  text. docs/mcp.md says so and recommends a read-only token when posting is off.

## Alternatives

- **Pass the context JSON between tools, as the skill passes files.** Lost because the agent would have
  to echo a context of tens of kilobytes back as an argument on every call, which costs its context
  window and invites copying mistakes. It would win for a stateless server behind HTTP.
- **Rebuild the context on every call.** Lost because each call would read GitHub again, and a push in
  between would check a result against lines the reviewer never saw.
- **MCP roots instead of `--root`.** The protocol lets a client tell the server which directories it may
  use. Lost for now because client support varies and the policy would then belong to whatever client
  connects, not to the user who started the server. It would win once every client sends roots.
- **An environment variable to allow posting.** Lost because a flag shows in the client's configuration
  next to the command, where a reader sees it, while a variable can be inherited from a shell without
  anyone noticing. One switch is enough.
- **Always list `post` and refuse it unless allowed.** Lost because an agent that sees a tool tends to try
  it, and a refusal at call time is one more thing a hostile pull request can ask for.
- **The low-level `Server` API.** Lost because `MCPServer` already turns typed functions into tool
  schemas, annotations and structured output, and bylaw has nothing to tune below that.
- **Streamable HTTP.** Lost because a local reviewer needs no network listener, and stdio needs no port,
  no authentication and no CORS policy. It would win for a shared, hosted server.
