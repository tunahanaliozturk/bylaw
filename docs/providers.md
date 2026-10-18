# Model providers

bylaw's own checks need no model. The model review, the part that reads the diff against your rules and
requirements, runs on the provider you pick with `--provider` (the Action's `provider` input). Teams that
cannot send code to a public API can keep it in their own cloud account, or on their own machine with a
local model.

Whichever provider you choose, the same brief goes to it: the pull request title, the diff with its file
paths, the rule files, the decision sections of accepted ADRs and the requirement text. Nothing else
leaves the machine for the model, and nothing goes to bylaw's authors. With Claude Code or Codex there is
no provider to pick: the host's own model reads the brief in your session ([hosts.md](hosts.md)).

## What leaves the machine, and where it goes

| Provider | `--provider` | Where the brief goes | Credentials, from the environment | Extra |
| --- | --- | --- | --- | --- |
| Claude API | `anthropic` | Anthropic, under your API account | `ANTHROPIC_API_KEY` or `BYLAW_API_KEY` | none |
| OpenAI API | `openai` | OpenAI, under your API account; bylaw asks it not to store the response | `OPENAI_API_KEY` or `BYLAW_API_KEY` | none |
| Amazon Bedrock | `bedrock` | Claude in Amazon Bedrock, in your AWS account and the region you set | `AWS_REGION`, then a Bedrock API key in `AWS_BEARER_TOKEN_BEDROCK`, or the AWS credential chain: `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY`, `AWS_PROFILE`, SSO or a role | `bedrock`, for signing with the credential chain |
| Google Vertex AI | `vertex` | Claude on Vertex AI, in your Google Cloud project and the region you set (`global`, `us`, `eu` or one region) | `CLOUD_ML_REGION`, `ANTHROPIC_VERTEX_PROJECT_ID`, and Application Default Credentials: `gcloud auth application-default login`, `GOOGLE_APPLICATION_CREDENTIALS` or workload identity | `vertex` |
| Microsoft Foundry | `foundry` | Claude in your Foundry resource, under Anthropic's data use terms as Microsoft's processor. Hosted on Azure, prompts and completions stay in Azure, but usage metadata and content Anthropic's safety systems flag go to Anthropic; hosted on Anthropic, inference runs on Anthropic's infrastructure | `ANTHROPIC_FOUNDRY_RESOURCE` (or `ANTHROPIC_FOUNDRY_BASE_URL`), then `ANTHROPIC_FOUNDRY_API_KEY` or Microsoft Entra ID | `azure`, for Entra ID |
| Azure OpenAI | `azure-openai` | Your Azure OpenAI resource, in its region or the geography of a Global or Data Zone deployment; bylaw asks it not to store the response | `AZURE_OPENAI_ENDPOINT` (the resource URL; a copied `/openai/v1` is dropped), then `AZURE_OPENAI_API_KEY` or Microsoft Entra ID | `azure`, for Entra ID |
| A local model | `openai-compatible` | The server at `--base-url`. On `localhost` nothing leaves the machine; anywhere else it must be `https://` | none needed; `BYLAW_BASE_URL_KEY` (the Action's `base-url-api-key`) if the server wants a key | none |

Each cloud keeps to its own terms for what it logs and for how long; read them before you choose one:
[Amazon Bedrock data protection](https://docs.aws.amazon.com/bedrock/latest/userguide/data-protection.html),
[Claude on Vertex AI](https://platform.claude.com/docs/en/build-with-claude/claude-on-vertex-ai) and its
endpoint choices for data residency,
[Claude in Microsoft Foundry](https://platform.claude.com/docs/en/build-with-claude/claude-in-microsoft-foundry)
and its hosting options, and
[data, privacy and security for Azure OpenAI](https://learn.microsoft.com/en-us/azure/ai-foundry/responsible-ai/openai/data-privacy),
which covers abuse monitoring.

The extras install each cloud's own sign-in library, so that people who use one provider do not install
the others: `pip install 'bylaw[bedrock]'`, `'bylaw[vertex]'` or `'bylaw[azure]'`, or with uv,
`uvx --from 'bylaw[vertex]' bylaw review ...`. The Action installs the right one from its `provider` input.

## How credentials are handled

bylaw reads credentials only from each provider's standard variables and credential chain, the ones that
provider's own SDK and command line tools read. It never writes them to files, logs or comments, and an
error note names the provider, the status code and the error type only, because a provider's error
message can quote part of a key and the note may be public.

A key meant for one provider is never sent to another. `BYLAW_API_KEY`, the Action's `api-key` input, is
used only by `anthropic` and `openai`. The cloud providers and the local one ignore it, because a key left
over from an earlier `provider` setting would otherwise travel to a different company, or to whatever
server `--base-url` names. A local server gets its own `BYLAW_BASE_URL_KEY` and nothing else: not
`OPENAI_API_KEY`, and not the `OPENAI_ORG_ID` or `OPENAI_PROJECT_ID` the OpenAI SDK would add. Azure
OpenAI gets neither of those either.

Two more variables would break that rule, so bylaw stops with a note when they are set:
`OPENAI_CUSTOM_HEADERS` for `openai-compatible` and `azure-openai`, and `ANTHROPIC_CUSTOM_HEADERS` for
`foundry`. The SDKs add the headers listed there to every request, an `Authorization` line included.

A key variable that is set but empty, which is what a workflow leaves when it passes a secret that does
not exist, also stops the review with a note. Left alone, the SDK would send an empty key in place of
signing in with the credential chain.

A credential chain that finds nothing, or a token that cannot be refreshed, fails the model review with a
note, and bylaw's own checks still run. Any other error is a bug and stops the run, so that it cannot hide
behind a note while `fail-on` passes.

## Model names

| Provider | Default | Notes |
| --- | --- | --- |
| `anthropic`, `vertex`, `foundry` | `claude-opus-5-5` | On Foundry, the model is the deployment name, which defaults to the model id |
| `bedrock` | `anthropic.claude-opus-5-5` | Model ids on Claude in Amazon Bedrock carry the `anthropic.` prefix |
| `openai` | none, `--model` is required | bylaw does not guess model names |
| `azure-openai` | none, `--model` is required | The deployment name, not the model name |
| `openai-compatible` | none, `--model` is required | The name the server lists, such as `qwen3:4b` on Ollama |

## Structured output and the JSON fallback

The Claude API, Vertex AI, Foundry, OpenAI and Azure OpenAI constrain the answer to bylaw's review schema
(structured outputs), so the answer parses. Claude in Amazon Bedrock does not offer structured outputs,
and a local server may not either, or may accept the setting and not enforce it. For those, bylaw writes
the schema into the prompt, checks the answer against it, and sends a wrong answer back once with what
was wrong, by field path. A second wrong answer fails the model review with a note that names the
problems; bylaw's own checks still run and post. The problems name only the schema's own fields and list
indexes, because a field name the model made up is its text and the note may be public.

The answer may come with a thinking block, prose or a code fence around it: bylaw drops `<think>` blocks
and takes the first JSON object that decodes. An empty answer counts as no review and is not sent back.

The retry is a second call, so on a paid provider it is billed, and the token count in the summary
includes it. With `[budget] pr_tokens` set, bylaw skips the retry when the tokens used so far plus another
input of the same size would pass what is left. In the fallback the brief is marked for the prompt cache,
so a retry on Bedrock reads it at the cache price ([ADR 0018](adr/0018-model-providers.md)).

Of these providers only the Claude API has server-side fallback, which retries a refused answer on
another model, so bylaw asks for it only there.

## A local model

Any server that speaks the OpenAI Chat Completions API works: Ollama, vLLM or LM Studio.

```
ollama pull qwen3:4b
bylaw review --context context.json --provider openai-compatible \
  --base-url http://localhost:11434/v1 --model qwen3:4b
```

A small model finds less than a large one, and the evaluation set says how much less
([eval/README](eval/README.md)).

Mind the context length. Ollama gives a model 4k tokens of context on a machine with less than 24 GiB of
VRAM (32k up to 48 GiB, 256k above), and a brief is often longer: the rules, the ADRs and the diff
together. Ollama cuts what does not fit and the request still succeeds, so the model reviews part of the
change. Start
the server with a larger context, for example `OLLAMA_CONTEXT_LENGTH=32768 ollama serve`, or lower
`input_token_budget` in `.bylaw.toml` to what the model can hold
([Ollama: context length](https://docs.ollama.com/context-length)).

In the Action, the server has to be reachable from the runner, which usually means a self-hosted runner
next to it. bylaw refuses plain `http://` unless the server is on the same machine (`localhost`,
`127.0.0.1` or `::1`): the brief holds your code, and plain `http://` would send it across the network in
clear text. Put TLS in front of a server elsewhere, or reach it through a tunnel to `localhost`.

## In the Action

Sign in to the cloud in an earlier step, with your cloud's own login action and OpenID Connect rather
than a long-lived key where you can, and put the rest of the variables in the job's `env`. The Action's
step inherits them.

```yaml
jobs:
  review:
    runs-on: ubuntu-latest
    permissions:
      contents: read
      pull-requests: write
      issues: read
      id-token: write # for the cloud's OpenID Connect sign-in
    env:
      AWS_REGION: eu-west-1
    steps:
      # A step that signs in to AWS goes here.
      - uses: tunahanaliozturk/bylaw@v0
        with:
          provider: bedrock
```

For Vertex AI set `CLOUD_ML_REGION` and `ANTHROPIC_VERTEX_PROJECT_ID`; for Foundry
`ANTHROPIC_FOUNDRY_RESOURCE`; for Azure OpenAI `AZURE_OPENAI_ENDPOINT` and `model: <deployment>`. A key,
where you use one, belongs in a secret passed through `env`, never in `.bylaw.toml`.

## In the GitHub App

The self-hosted GitHub App offers only `anthropic` and `openai`. The other providers would sign in with
the server's own credentials, the same ones for every installation, and the app never lets a server-wide
credential review for an installation ([app/deploy.md](app/deploy.md)).
