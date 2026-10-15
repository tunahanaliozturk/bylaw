# 0001: Deterministic core, swappable reasoner

Status: Accepted, 2026-10-15

## Context

bylaw has to run in three places: a GitHub Action, Claude Code and Codex. In the Action nobody is driving
a model, so bylaw must call one itself. In Claude Code and Codex a capable model is already running and
already paid for. Users trust review comments only when they can see why a comment was made, and a model
on its own will cite rules that do not exist.

## Decision

We build one deterministic core that collects context, validates findings and publishes them, and we let
the host supply the reasoning: the built-in engine with the user's key in the Action, the host model in
Claude Code and Codex.

## Consequences

- Rule parsing, criteria extraction, validation and publishing are plain code with unit tests, and they
  behave the same in every mode.
- Claude Code and Codex users need no extra API key.
- The validator can reject invented citations because the core knows every rule file and line it
  collected.
- Cost: this is the most code of the options considered. The CLI surface (`context`, `validate`, `post`,
  `prompts`) becomes a public interface the skills depend on, so changing it needs care.
- Review quality varies by host model, which makes eval results per model rather than per release.

## Alternatives

- **Prompt-only skill**, run in the Action through vendor actions. Lost because nothing could be tested,
  the project would depend on third party actions, and the only asset would be a prompt anyone can copy.
  It would win for a one-week experiment.
- **MCP server as the core.** Lost because the Action would need a headless agent loop around it, more
  moving parts for no gain over a CLI. It would win if most users came from MCP-only clients. It can
  still be added later as a thin wrapper over the CLI.
