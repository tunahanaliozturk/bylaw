# More model providers

Roadmap: Q3 in [ROADMAP.md](../ROADMAP.md). Target: v0.6. Item ids: `PRV-n`.

Teams that cannot send code to a public API need Bedrock, Vertex, Azure or a local model.

**Done when** each provider works through `--provider`, and its evaluation is published.

## Items

- [x] **PRV-1** (M) Amazon Bedrock through the Anthropic SDK's Bedrock client. Done when: fake transport tests.
- [x] **PRV-2** (M) Google Vertex AI through the Anthropic SDK's Vertex client. Done when: fake transport tests.
- [x] **PRV-3** (M) Azure: Claude through Microsoft Foundry, and Azure OpenAI. Done when: fake transport tests.
- [x] **PRV-4** (M) OpenAI-compatible base URL for local models (Ollama, vLLM), with a JSON fallback. Done when: tests.
- [x] **PRV-5** (M) Evaluation per provider and model. Done when: reports committed. Done for the paths that need no cloud account: the Claude API (eval/results/2026-10-19-opus-5-5-v0.5) and the `openai-compatible` provider against Anthropic's OpenAI-compatible endpoint with the same model (eval/results/2026-10-19-openai-compatible-opus-5-5), which runs the strict-format request, the JSON fallback and the retry against a real server. Bedrock, Vertex AI and Azure runs wait for accounts; they are on the live checks list.
- [x] **PRV-6** (S) Docs table: what leaves the machine with each provider. Done when: docs page.

## Notes

Local models often lack strict structured output; the fallback validates and retries.

PRV-5 status: both reports above are committed. Still to run, by someone with the account: Bedrock, Vertex AI, Foundry and Azure OpenAI, and a small local model under Ollama (its default context window is small; see docs/providers.md).
