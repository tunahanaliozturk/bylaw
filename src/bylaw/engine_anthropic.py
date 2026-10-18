"""Reviews with Claude through the official Anthropic SDK: the Claude API, Amazon Bedrock, Google Vertex AI
and Microsoft Foundry. Structured outputs where the platform has them, the JSON fallback where not."""

import os
from importlib.util import find_spec
from typing import Literal, cast

import anthropic
import httpx2
from anthropic.types.beta import BetaMessageParam, BetaOutputConfigParam, BetaTextBlockParam
from pydantic import ValidationError

from bylaw.engine import (
    OutReview,
    Retry,
    ReviewError,
    Usage,
    added,
    entra_token_provider,
    json_instructions,
    review_with_retry,
)
from bylaw.model import ReviewResult

DEFAULT_MODEL = "claude-opus-5-5"
# Model ids on Claude in Amazon Bedrock carry the provider prefix.
BEDROCK_DEFAULT_MODEL = "anthropic.claude-opus-5-5"
# Streamed, so no request-time ceiling applies. A review is a few thousand tokens of JSON plus thinking;
# the headroom is for large pull requests at high effort, where a cut-off answer would lose the review.
_MAX_TOKENS = 64_000
_STREAM_ATTEMPTS = 2
_FALLBACK_BETA = "server-side-fallback-2026-07-01"
# Server-side fallback routes a safety refusal to another model; security review text can trip the
# cyber classifier, so it is on wherever the model supports it.
_FALLBACK_MODELS = frozenset({"claude-opus-5-5", "claude-opus-5", "claude-fable-5-1", "claude-sonnet-5-5"})
_BEDROCK_KEYS = ("AWS_BEARER_TOKEN_BEDROCK", "ANTHROPIC_AWS_API_KEY")

type Client = anthropic.Anthropic | anthropic.AnthropicBedrockMantle


class AnthropicReviewer:
    def __init__(  # noqa: PLR0913 - one reviewer for four platforms, which differ in these
        self,
        *,
        client: Client,
        model: str,
        effort: str | None,
        service: str = "the Anthropic API",
        structured: bool = True,
        server_fallback: bool = True,
    ) -> None:
        self._client = client
        self._model = model
        self._effort = effort or "high"
        self._service = service
        self._structured = structured
        self._fallback = server_fallback and model in _FALLBACK_MODELS
        self.last_usage: Usage | None = None

    def review(self, system: str, user: str) -> ReviewResult:
        self.last_usage = None
        if not self._structured:
            return review_with_retry(lambda retry: self._ask(system + json_instructions(), user, retry))
        text = self._ask(system, user, None)
        try:
            return OutReview.model_validate_json(text).to_result()
        except ValidationError as error:
            raise ReviewError("the model returned output that is not a valid review") from error

    def _ask(self, system: str, user: str, retry: Retry | None) -> str:
        system_blocks: list[BetaTextBlockParam] = [
            {"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}
        ]
        messages: list[BetaMessageParam] = [{"role": "user", "content": user}]
        if retry:
            messages += [{"role": "assistant", "content": retry[0]}, {"role": "user", "content": retry[1]}]
        # effort is a free string on the CLI; the API rejects an unknown level with a clear 400.
        config: dict[str, object] = {"effort": self._effort}
        if self._structured:
            config["format"] = {"type": "json_schema", "schema": anthropic.transform_schema(OutReview)}
        output_config = cast(BetaOutputConfigParam, config)
        fallbacks: Literal["default"] | anthropic.Omit = "default" if self._fallback else anthropic.omit
        try:
            for attempt in range(_STREAM_ATTEMPTS):
                try:
                    # Streamed without the SDK's parse helper: the stop reason is read before the JSON is
                    # validated, so a refusal or a truncated answer is reported as such.
                    with self._client.beta.messages.stream(
                        model=self._model,
                        max_tokens=_MAX_TOKENS,
                        system=system_blocks,
                        messages=messages,
                        thinking={"type": "adaptive"},
                        output_config=output_config,
                        betas=[_FALLBACK_BETA] if self._fallback else anthropic.omit,
                        fallbacks=fallbacks,
                    ) as stream:
                        response = stream.get_final_message()
                    break
                except httpx2.TransportError as error:
                    # A connection lost mid-stream is not retried by the SDK; one more try, then a clear note.
                    if attempt == _STREAM_ATTEMPTS - 1:
                        raise ReviewError(
                            f"the connection to {self._service} dropped before the review finished"
                        ) from error
        except anthropic.APIStatusError as error:
            # Status and error type only: the message can quote request details and the note is public.
            raise ReviewError(
                f"{self._service} returned {error.status_code} ({_error_type(error.body)})"
            ) from error
        except anthropic.APIConnectionError as error:
            raise ReviewError(f"could not reach {self._service}") from error
        except (anthropic.AnthropicError, ValueError) as error:
            raise ReviewError(f"the Anthropic SDK rejected the request ({type(error).__name__})") from error
        except ReviewError:
            raise
        except Exception as error:
            # A cloud credential chain (botocore, google-auth) raises its own errors from inside the request
            # when it finds no credentials or cannot refresh them. The review fails with a note, not the run.
            raise ReviewError(
                f"the request to {self._service} failed ({type(error).__name__}); check its credentials"
            ) from error
        # Recorded first: a refused or truncated answer is billed too, and so is the first of two tries.
        usage = response.usage
        self.last_usage = added(
            self.last_usage,
            usage.input_tokens
            + (usage.cache_read_input_tokens or 0)
            + (usage.cache_creation_input_tokens or 0),
            usage.output_tokens,
        )
        if response.stop_reason == "refusal":
            category = response.stop_details.category if response.stop_details else None
            raise ReviewError(f"the model declined to review this change ({category or 'no category'})")
        if response.stop_reason == "max_tokens":
            raise ReviewError("the model ran out of output tokens before finishing the review")
        return "".join(block.text for block in response.content if block.type == "text")


def bedrock_reviewer(
    model: str | None, effort: str | None, http_client: httpx2.Client | None
) -> AnthropicReviewer:
    """Claude in Amazon Bedrock, the Messages API endpoint. It has no structured outputs and no server-side
    fallback (ADR 0018). Credentials and region come from the AWS chain: a Bedrock API key in
    AWS_BEARER_TOKEN_BEDROCK, or SigV4 with AWS_ACCESS_KEY_ID, a profile, SSO or a role."""
    # SigV4 signing needs botocore; a Bedrock API key does not.
    if not any(os.environ.get(name) for name in _BEDROCK_KEYS) and not _installed("botocore"):
        raise ReviewError(
            "signing Amazon Bedrock requests needs the bedrock extra: pip install 'bylaw[bedrock]'"
        )
    try:
        client = anthropic.AnthropicBedrockMantle(http_client=http_client, max_retries=3)
    except (anthropic.AnthropicError, ValueError) as error:
        # The SDK's own setup message: it names the missing variable and never holds a credential.
        raise ReviewError(f"Amazon Bedrock is not set up: {error}") from error
    return AnthropicReviewer(
        client=client,
        model=model or BEDROCK_DEFAULT_MODEL,
        effort=effort,
        service="Amazon Bedrock",
        structured=False,
        server_fallback=False,
    )


def vertex_reviewer(
    model: str | None, effort: str | None, http_client: httpx2.Client | None
) -> AnthropicReviewer:
    """Claude on Google Cloud's Vertex AI, with structured outputs but no server-side fallback (ADR 0018).
    Credentials are Application Default Credentials; the region and project come from CLOUD_ML_REGION and
    ANTHROPIC_VERTEX_PROJECT_ID."""
    if not _installed("google.auth"):
        raise ReviewError(
            "Vertex AI needs the vertex extra for Google credentials: pip install 'bylaw[vertex]'"
        )
    # Checked here: the SDK would find the missing project only inside the request, as a RuntimeError.
    if os.environ.get("CLOUD_ML_REGION") and not os.environ.get("ANTHROPIC_VERTEX_PROJECT_ID"):
        raise ReviewError(
            "Vertex AI is not set up: set ANTHROPIC_VERTEX_PROJECT_ID to the Google Cloud project"
        )
    try:
        client = anthropic.AnthropicVertex(http_client=http_client, max_retries=3)
    except (anthropic.AnthropicError, ValueError) as error:
        raise ReviewError(f"Vertex AI is not set up: {error}") from error
    return AnthropicReviewer(
        # Vertex's messages resource reuses the first-party stream method, whose self the SDK types as the
        # first-party resource; the call is the same.
        client=cast(anthropic.Anthropic, client),
        model=model or DEFAULT_MODEL,
        effort=effort,
        service="Vertex AI",
        server_fallback=False,
    )


def foundry_reviewer(
    model: str | None, effort: str | None, http_client: httpx2.Client | None
) -> AnthropicReviewer:
    """Claude in Microsoft Foundry, with structured outputs but no server-side fallback (ADR 0018). The key is
    ANTHROPIC_FOUNDRY_API_KEY; without one, Microsoft Entra ID. The resource is ANTHROPIC_FOUNDRY_RESOURCE or
    ANTHROPIC_FOUNDRY_BASE_URL."""
    has_key = bool(os.environ.get("ANTHROPIC_FOUNDRY_API_KEY"))
    tokens = None if has_key else entra_token_provider("ANTHROPIC_FOUNDRY_API_KEY")
    try:
        client = anthropic.AnthropicFoundry(
            azure_ad_token_provider=tokens, http_client=http_client, max_retries=3
        )
    except (anthropic.AnthropicError, ValueError) as error:
        raise ReviewError(f"Microsoft Foundry is not set up: {error}") from error
    return AnthropicReviewer(
        client=client,
        model=model or DEFAULT_MODEL,
        effort=effort,
        service="Microsoft Foundry",
        server_fallback=False,
    )


def _installed(module: str) -> bool:
    try:
        return find_spec(module) is not None
    except ModuleNotFoundError:  # the parent package is missing too
        return False


def _error_type(body: object) -> str:
    error = body.get("error") if isinstance(body, dict) else None
    kind = error.get("type") if isinstance(error, dict) else None
    return kind if isinstance(kind, str) else "unknown error"
