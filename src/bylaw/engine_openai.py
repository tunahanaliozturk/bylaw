"""Reviews through the official OpenAI SDK: OpenAI and Azure OpenAI with structured outputs, and any
server that speaks Chat Completions (Ollama, vLLM, LM Studio) with the JSON fallback."""

from typing import Any, cast

import openai
from openai.types.chat import ChatCompletion, ChatCompletionMessageParam
from openai.types.shared_params import Reasoning
from pydantic import ValidationError

from bylaw.engine import OutReview, Retry, ReviewError, Usage, added, json_instructions, review_with_retry
from bylaw.model import ReviewResult


class OpenAIReviewer:
    def __init__(
        self, *, client: openai.OpenAI, model: str, effort: str | None, service: str = "the OpenAI API"
    ) -> None:
        self._client = client
        self._model = model
        self._effort = effort
        self._service = service
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
                # Reviews hold private code; nothing needs to stay on the provider's side after the answer.
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
                f"{self._service} returned {error.status_code} ({error.code or 'unknown error'})"
            ) from error
        except openai.APIConnectionError as error:
            raise ReviewError(f"could not reach {self._service}") from error
        except ValidationError as error:
            # A truncated answer is not valid JSON; the SDK validates it before returning.
            raise ReviewError("the model returned output that is not a valid review") from error
        except (openai.OpenAIError, ValueError) as error:
            raise ReviewError(f"the OpenAI SDK rejected the request ({type(error).__name__})") from error
        if response.output_parsed is None:
            raise ReviewError("the model declined or returned no review")
        return response.output_parsed.to_result()


_SCHEMA_FORMAT: dict[str, Any] = {
    "type": "json_schema",
    "json_schema": {"name": "review", "schema": OutReview.model_json_schema(), "strict": True},
}


class ChatReviewer:
    """Chat Completions, the API every OpenAI-compatible server has. The schema is asked for as a strict
    response format and also written into the prompt, and the answer is checked either way: a server may
    reject the format, or accept it and not enforce it."""

    def __init__(self, *, client: openai.OpenAI, model: str, effort: str | None) -> None:
        self._client = client
        self._model = model
        self._effort = effort
        self._strict = True
        self.last_usage: Usage | None = None

    def review(self, system: str, user: str) -> ReviewResult:
        self.last_usage = None
        return review_with_retry(lambda retry: self._ask(system + json_instructions(), user, retry))

    def _ask(self, system: str, user: str, retry: Retry | None) -> str:
        messages: list[ChatCompletionMessageParam] = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]
        if retry:
            messages += [{"role": "assistant", "content": retry[0]}, {"role": "user", "content": retry[1]}]
        try:
            completion = self._complete(messages)
        except openai.APIStatusError as error:
            # The status only: a server's message can echo the request, and the note is public.
            raise ReviewError(f"the server at the base URL returned {error.status_code}") from error
        except openai.APIConnectionError as error:
            raise ReviewError("could not reach the server at the base URL") from error
        except (openai.OpenAIError, ValueError) as error:
            raise ReviewError(f"the OpenAI SDK rejected the request ({type(error).__name__})") from error
        if completion.usage:
            usage = completion.usage
            self.last_usage = added(self.last_usage, usage.prompt_tokens, usage.completion_tokens)
        choice = completion.choices[0] if completion.choices else None
        if choice is not None and choice.finish_reason == "length":
            raise ReviewError("the model ran out of output tokens before finishing the review")
        if choice is None or not choice.message.content:
            raise ReviewError("the model declined or returned no review")
        return choice.message.content

    def _complete(self, messages: list[ChatCompletionMessageParam]) -> ChatCompletion:
        effort = cast(Any, self._effort) if self._effort else openai.omit
        if self._strict:
            try:
                return self._client.chat.completions.create(
                    model=self._model,
                    messages=messages,
                    response_format=cast(Any, _SCHEMA_FORMAT),
                    reasoning_effort=effort,
                )
            except (openai.BadRequestError, openai.UnprocessableEntityError):
                # No strict structured output on this server: the prompt still holds the schema, and the
                # answer is still checked. Remembered, so the retry does not try the format again.
                self._strict = False
        return self._client.chat.completions.create(
            model=self._model, messages=messages, reasoning_effort=effort
        )


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
