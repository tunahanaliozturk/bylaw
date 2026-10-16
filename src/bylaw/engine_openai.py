"""Reviews with an OpenAI model through the official OpenAI SDK and structured outputs."""

from typing import cast

import openai
from openai.types.shared_params import Reasoning
from pydantic import ValidationError

from bylaw.engine import OutReview, ReviewError, Usage
from bylaw.model import ReviewResult


class OpenAIReviewer:
    def __init__(
        self,
        *,
        model: str,
        effort: str | None,
        api_key: str | None,
        http_client: openai.DefaultHttpxClient | None = None,
    ) -> None:
        self._model = model
        self._effort = effort
        self._client = openai.OpenAI(api_key=api_key, http_client=http_client, max_retries=3)
        self.last_usage: Usage | None = None

    def review(self, system: str, user: str) -> ReviewResult:
        self.last_usage = None
        reasoning = cast(Reasoning, {"effort": self._effort}) if self._effort else openai.omit
        try:
            # Raw first: a truncated answer fails to parse, but its tokens were billed and are in the body.
            raw = self._client.responses.with_raw_response.parse(
                model=self._model,
                instructions=system,
                input=user,
                text_format=OutReview,
                reasoning=reasoning,
                # Reviews hold private code; nothing needs to stay on OpenAI's side after the answer.
                store=False,
            )
            body = raw.http_response.json()
            self.last_usage = _usage(body)
            if _ran_out(body):
                raise ReviewError("the model ran out of output tokens before finishing the review")
            response = raw.parse()
        except openai.APIStatusError as error:
            # Status and error code only: OpenAI's message quotes part of a wrong key, and the note is public.
            raise ReviewError(
                f"OpenAI API returned {error.status_code} ({error.code or 'unknown error'})"
            ) from error
        except openai.APIConnectionError as error:
            raise ReviewError("could not reach the OpenAI API") from error
        except ValidationError as error:
            # A truncated answer is not valid JSON; the SDK validates it before returning.
            raise ReviewError("the model returned output that is not a valid review") from error
        except (openai.OpenAIError, ValueError) as error:
            raise ReviewError(f"the OpenAI SDK rejected the request ({type(error).__name__})") from error
        if response.output_parsed is None:
            raise ReviewError("the model declined or returned no review")
        return response.output_parsed.to_result()


def _usage(body: object) -> Usage | None:
    usage = body.get("usage") if isinstance(body, dict) else None
    if not isinstance(usage, dict):
        return None
    tokens_in, tokens_out = usage.get("input_tokens"), usage.get("output_tokens")
    if isinstance(tokens_in, int) and isinstance(tokens_out, int):
        return Usage(tokens_in, tokens_out)
    return None


def _ran_out(body: object) -> bool:
    details = body.get("incomplete_details") if isinstance(body, dict) else None
    return isinstance(details, dict) and details.get("reason") == "max_output_tokens"
