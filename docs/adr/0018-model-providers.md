# 0018: Cloud and local model providers behind the same reviewer

Status: Accepted, 2026-10-18. Builds on 0001.

## Context

Until now the model review ran on the Claude API or the OpenAI API with the user's key. Teams that may not
send code to a public API asked for their own cloud account (Amazon Bedrock, Google Vertex AI, Microsoft
Foundry, Azure OpenAI) or a model on their own hardware. These differ in three ways that matter to bylaw:

- **Credentials.** The clouds sign requests through their own credential chains (AWS SigV4, Google
  Application Default Credentials, Microsoft Entra ID), not with one API key, and bylaw cannot tell whether
  a chain will find anything without calling it.
- **Structured outputs.** The Claude API, Vertex AI, Foundry, OpenAI and Azure OpenAI constrain the answer
  to a JSON schema. Claude in Amazon Bedrock does not
  ([structured outputs, compatibility](https://platform.claude.com/docs/en/build-with-claude/structured-outputs)),
  and local servers vary: some reject a strict schema, some accept it and do not enforce it.
- **Server-side fallback.** Only the Claude API has it; Bedrock, Vertex AI and Foundry list it as not
  supported.

## Decision

We keep one reviewer per SDK and give it a client that each provider builds its own way. Claude on all four
platforms goes through the Anthropic SDK's own clients (`AnthropicBedrockMantle` for Claude in Amazon
Bedrock, `AnthropicVertex`, `AnthropicFoundry`), and Azure OpenAI and local servers through the OpenAI SDK.
Per provider we record only what differs: the client, whether structured outputs exist, whether server-side
fallback exists, and the name an error note uses.

Credentials come only from each provider's standard variables and chains. `BYLAW_API_KEY` is for the
Claude and OpenAI APIs only; a local server gets its own `BYLAW_BASE_URL_KEY`, because `--base-url` can
name any host. No client is left to fall back to `ANTHROPIC_API_KEY` or `OPENAI_API_KEY`, the OpenAI
client's organization and project ids are cleared for Azure and local servers, and a set
`OPENAI_CUSTOM_HEADERS` or `ANTHROPIC_CUSTOM_HEADERS` is refused where its headers would reach another
provider. A key variable set but empty is refused rather than sent as an empty key. Plain `http://` is
refused for a server that is not on the same machine.

Every cloud provider is tried when it is chosen. A chain that finds nothing fails the model review with a
note, and bylaw's own checks still run. Only what a chain raises becomes a note: botocore, google-auth and
azure-identity errors, the SDKs' credential `RuntimeError`s and an `ImportError` from a missing piece of an
extra, and only for the cloud providers. Anything else, such as a `TypeError` after an SDK upgrade, is a
bug and stops the run, so that it cannot pass `fail-on` as a quiet note.

Where structured outputs are missing or not trusted, the JSON fallback: the schema goes into the prompt,
the answer is validated against it, and a wrong answer goes back once with its problems by field path.
A second failure is a `ReviewError`. The answer is read after dropping `<think>` blocks, from the first JSON
object that decodes, and an empty answer is no review. The problems never quote the answer and name only
the schema's fields and indexes, because that text came from the model and the note may be posted. The
retry is skipped when it would pass what is left of `[budget] pr_tokens`, and in the fallback the brief is
marked for the prompt cache so a retry reads it at the cache price. For local servers bylaw also asks for
the schema as a strict response format, and drops that request when the server answers 400 or 422.

The cloud sign-in libraries are optional extras (`bylaw[bedrock]`, `bylaw[vertex]`, `bylaw[azure]`); the
development environment installs them so the tests and the licence audit cover them.

## Consequences

- A user picks a provider with one flag and the variables their cloud's own tools already use. The privacy
  table in [providers.md](../providers.md) is the same list of variables.
- Leaving `BYLAW_API_KEY` out of the clouds and local servers means the Action's `api-key` input does
  nothing for them; keys for Bedrock or Foundry go in `env`, and a local server's in `base-url-api-key`.
  A key from an earlier `provider` cannot reach another company or another host.
- A user who set `OPENAI_CUSTOM_HEADERS` for the OpenAI API has to unset it for Azure or a local server.
  We prefer that to guessing which of their headers are safe to pass on.
- A local server on another machine needs TLS or a tunnel. There is no opt-in for plain `http://`, because
  the brief is the pull request's code.
- Bedrock reviews are less certain to parse than those on platforms with structured outputs, and a retry
  is a second paid call. Its tokens count towards `[budget] pr_tokens`.
- The `RuntimeError` caught for the clouds is wider than the SDKs' credential errors alone; a cloud bug
  that raises one would become a note. The first-party providers catch only their SDK's errors and `ValueError`, as before.
- Nothing here has been run against a live cloud account: every provider is tested through a fake
  transport, with the SDK's real request building and, for Bedrock, the real SigV4 signer. Evaluation
  reports per provider and model (PRV-5) are still to come.
- The GitHub App offers only `anthropic` and `openai`. The other providers sign in with the server's own
  environment, which every installation would share, and ADR 0017 never lets a server-wide credential
  review for an installation. Per-installation cloud credentials would be the way to add them.
- Cost: four more clients to keep working across SDK releases, and an optional-dependency surface.

## Alternatives

- **The legacy Bedrock client (`AnthropicBedrock`, InvokeModel).** It has structured outputs, but only for
  Claude 4.6 and earlier models; current models are on the Messages API endpoint that
  `AnthropicBedrockMantle` calls. It would win for a team pinned to an older model.
- **The newer platform clients (`AnthropicAWS`, `AnthropicGoogleCloud`).** They give the full Claude API
  with cloud billing, but the SDK marks their names and variables as provisional. They can be added once
  they settle.
- **Only the fallback, everywhere.** Simpler, but it gives up the guarantee structured outputs give where
  they exist.
- **A key check for the clouds, as for the APIs.** Lost because a chain can find credentials no variable
  shows (an instance role, `az login`), so a check would skip reviews that would have worked.
- **LiteLLM or a similar router.** Lost because it is a large dependency between bylaw and SDKs it already
  uses directly, and its own request shapes would hide the provider differences above rather than state
  them.
