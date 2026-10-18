# More model providers

Roadmap: Q3 in [ROADMAP.md](../ROADMAP.md). Target: v0.6. Item ids: `PRV-n`.

Teams that cannot send code to a public API need Bedrock, Vertex, Azure or a local model.

**Done when** each provider works through `--provider`, and its evaluation is published.

## Items

- [x] **PRV-1** (M) Amazon Bedrock through the Anthropic SDK's Bedrock client. Done when: fake transport tests.
- [x] **PRV-2** (M) Google Vertex AI through the Anthropic SDK's Vertex client. Done when: fake transport tests.
- [x] **PRV-3** (M) Azure: Claude through Microsoft Foundry, and Azure OpenAI. Done when: fake transport tests.
- [x] **PRV-4** (M) OpenAI-compatible base URL for local models (Ollama, vLLM), with a JSON fallback. Done when: tests.
- [ ] **PRV-5** (M) Evaluation per provider and model. Done when: reports committed.
- [ ] **PRV-6** (S) Docs table: what leaves the machine with each provider. Done when: docs page.

## Notes

Local models often lack strict structured output; the fallback validates and retries.

PRV-5 status: `bylaw eval run` takes every provider, records `provider:model:effort` as the reviewer and keeps `--max-cost` for all of them. No report is committed yet. The no-cost run with a small local model through `openai-compatible` needs a machine with Ollama (or vLLM or LM Studio); the cloud runs need accounts and are paid, so they wait for a maintainer with credentials.
