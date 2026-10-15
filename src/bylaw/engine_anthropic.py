"""Reviews with Claude through the official Anthropic SDK and structured outputs."""

from typing import Literal, cast

import anthropic
from anthropic.types.beta import BetaMessageParam, BetaOutputConfigParam, BetaTextBlockParam
from pydantic import ValidationError

from bylaw.engine import OutReview, ReviewError
from bylaw.model import ReviewResult

DEFAULT_MODEL = "claude-opus-5-5"
# Non-streaming stays under the SDK's ten-minute request ceiling at this size; a review is a few
# thousand tokens of JSON plus thinking.
_MAX_TOKENS = 20_000
_FALLBACK_BETA = "server-side-fallback-2026-07-01"
# Server-side fallback routes a safety refusal to another model; security review text can trip the
# cyber classifier, so it is on wherever the model supports it.
_FALLBACK_MODELS = frozenset({"claude-opus-5-5", "claude-opus-5", "claude-fable-5-1", "claude-sonnet-5-5"})


class AnthropicReviewer:
    def __init__(
        self,
        *,
        model: str,
        effort: str,
        api_key: str | None,
        http_client: anthropic.DefaultHttpxClient | None = None,
    ) -> None:
        self._model = model
        self._effort = effort
        self._client = anthropic.Anthropic(api_key=api_key, http_client=http_client, max_retries=3)

    def review(self, system: str, user: str) -> ReviewResult:
        fallback = self._model in _FALLBACK_MODELS
        system_blocks: list[BetaTextBlockParam] = [
            {"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}
        ]
        messages: list[BetaMessageParam] = [{"role": "user", "content": user}]
        # effort is a free string on the CLI; the API rejects an unknown level with a clear 400.
        output_config = cast(
            BetaOutputConfigParam,
            {
                "effort": self._effort,
                "format": {"type": "json_schema", "schema": anthropic.transform_schema(OutReview)},
            },
        )
        fallbacks: Literal["default"] | anthropic.Omit = "default" if fallback else anthropic.omit
        try:
            # create, not parse: parse validates the JSON before the stop reason can be read, so a
            # refusal or a truncated answer would surface as a bare validation error.
            response = self._client.beta.messages.create(
                model=self._model,
                max_tokens=_MAX_TOKENS,
                system=system_blocks,
                messages=messages,
                thinking={"type": "adaptive"},
                output_config=output_config,
                betas=[_FALLBACK_BETA] if fallback else anthropic.omit,
                fallbacks=fallbacks,
            )
        except anthropic.APIStatusError as error:
            # Status and error type only: the message can quote request details and the note is public.
            raise ReviewError(
                f"Anthropic API returned {error.status_code} ({_error_type(error.body)})"
            ) from error
        except anthropic.APIConnectionError as error:
            raise ReviewError("could not reach the Anthropic API") from error
        except (anthropic.AnthropicError, ValueError) as error:
            raise ReviewError(f"the Anthropic SDK rejected the request ({type(error).__name__})") from error
        if response.stop_reason == "refusal":
            category = response.stop_details.category if response.stop_details else None
            raise ReviewError(f"the model declined to review this change ({category or 'no category'})")
        if response.stop_reason == "max_tokens":
            raise ReviewError("the model ran out of output tokens before finishing the review")
        text = "".join(block.text for block in response.content if block.type == "text")
        try:
            return OutReview.model_validate_json(text).to_result()
        except ValidationError as error:
            raise ReviewError("the model returned output that is not a valid review") from error


def _error_type(body: object) -> str:
    error = body.get("error") if isinstance(body, dict) else None
    kind = error.get("type") if isinstance(error, dict) else None
    return kind if isinstance(kind, str) else "unknown error"
