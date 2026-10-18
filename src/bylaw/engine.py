"""The model-facing review schema and the provider-neutral reviewer interface (ADR 0001)."""

import json
import os
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

import httpx2
from pydantic import BaseModel, ConfigDict, ValidationError

from bylaw.model import Category, CriterionStatus, ReviewResult, Severity

PROVIDERS = ("anthropic", "openai", "bedrock", "vertex", "openai-compatible")
_KEY_VARIABLES = {"anthropic": "ANTHROPIC_API_KEY", "openai": "OPENAI_API_KEY"}
# A local server needs no key, and a cloud provider authenticates through its own credential chain (an AWS
# profile or role, for one), which bylaw cannot see without calling it. Neither stops the model review.
_NO_KEY_NEEDED = frozenset({"bedrock", "vertex", "openai-compatible"})


class ReviewError(Exception):
    """The model review did not produce a result. The message is safe to print and never holds a key."""


@dataclass(frozen=True)
class Usage:
    """Tokens one review used. Cached input is counted as input, so a cost from it is an upper bound."""

    input_tokens: int
    output_tokens: int


# Strict structured outputs want every field required and no defaults, so the model-facing schema is
# separate from ReviewResult; nullable fields are `X | None` with no default.
class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class OutFinding(_Strict):
    file: str
    line_start: int
    line_end: int
    category: Category
    severity: Severity
    message: str
    suggestion: str | None
    evidence: str | None


class OutLocation(_Strict):
    file: str
    line: int


class OutCriterion(_Strict):
    criterion: str
    text: str | None
    status: CriterionStatus
    code: list[OutLocation]
    tests: list[OutLocation]
    note: str


class OutScopeCreep(_Strict):
    file: str
    line: int
    message: str


class OutReview(_Strict):
    findings: list[OutFinding]
    criteria: list[OutCriterion]
    scope_creep: list[OutScopeCreep]

    def to_result(self) -> ReviewResult:
        return ReviewResult.model_validate(self.model_dump())


class Reviewer(Protocol):
    def review(self, system: str, user: str) -> ReviewResult: ...


def api_key_for(provider: str) -> str | None:
    # The provider's own variable wins, so a key meant for one provider is never sent to another.
    return os.environ.get(_KEY_VARIABLES.get(provider, "")) or os.environ.get("BYLAW_API_KEY") or None


def key_variable(provider: str) -> str:
    """The variable that holds the provider's own key, for messages."""
    return _KEY_VARIABLES.get(provider, "BYLAW_API_KEY")


def can_review(provider: str) -> bool:
    """Whether the model review can be tried: a key is set, or the provider does not need one."""
    return provider in _NO_KEY_NEEDED or api_key_for(provider) is not None


def make_reviewer(  # noqa: PLR0913 - the base URL and the HTTP client are optional
    provider: str,
    model: str | None,
    effort: str | None,
    api_key: str | None,
    base_url: str | None = None,
    *,
    http_client: httpx2.Client | None = None,
) -> Reviewer:
    if base_url and provider != "openai-compatible":
        raise ReviewError("--base-url is only for the openai-compatible provider")
    if provider == "anthropic":
        import anthropic  # noqa: PLC0415 - load one SDK only

        from bylaw.engine_anthropic import DEFAULT_MODEL, AnthropicReviewer  # noqa: PLC0415

        claude = anthropic.Anthropic(api_key=api_key, http_client=http_client, max_retries=3)
        return AnthropicReviewer(client=claude, model=model or DEFAULT_MODEL, effort=effort)
    if provider == "bedrock":
        from bylaw.engine_anthropic import bedrock_reviewer  # noqa: PLC0415 - load one SDK only

        return bedrock_reviewer(model, effort, http_client)
    if provider == "vertex":
        from bylaw.engine_anthropic import vertex_reviewer  # noqa: PLC0415 - load one SDK only

        return vertex_reviewer(model, effort, http_client)
    import openai  # noqa: PLC0415 - load one SDK only

    from bylaw.engine_openai import ChatReviewer, OpenAIReviewer  # noqa: PLC0415

    if provider == "openai":
        client = openai.OpenAI(api_key=api_key, http_client=http_client, max_retries=3)
        return OpenAIReviewer(client=client, model=_named(model, provider), effort=effort)
    if provider == "openai-compatible":
        if not base_url:
            raise ReviewError("--base-url is required with the openai-compatible provider")
        # Always a key of its own: left empty, the SDK would read OPENAI_API_KEY and send it to this server.
        local = openai.OpenAI(
            api_key=api_key or "unused", base_url=base_url, http_client=http_client, max_retries=1
        )
        return ChatReviewer(client=local, model=_named(model, provider), effort=effort)
    raise ReviewError(f"unknown provider {provider!r}; use one of {', '.join(PROVIDERS)}")


def _named(model: str | None, provider: str) -> str:
    if not model:
        raise ReviewError(
            f"--model is required with the {provider} provider; bylaw does not guess model names"
        )
    return model


# The JSON fallback, for models and servers without strict structured output (ADR 0018): the schema goes
# in the prompt, the answer is checked against it, and a wrong answer is sent back once with its problems.
Retry = tuple[str, str]  # the answer that failed and what was wrong with it
_MAX_PROBLEMS = 8
_UNSAFE = re.compile(r"[^\w.\-]")


def json_instructions() -> str:
    schema = json.dumps(OutReview.model_json_schema(), separators=(",", ":"))
    return (
        "\n\nAnswer with one JSON object and nothing else: no prose before or after it. "
        f"It must follow this JSON schema exactly:\n{schema}"
    )


class InvalidReviewError(Exception):
    """What is wrong with an answer, by field path. It never quotes the answer: that text is the model's."""


def read_review(text: str) -> OutReview:
    # ponytail: the outermost braces, so prose or a code fence around the object does not matter; braces in
    # prose before the object would still confuse it, and the retry is there for that.
    start, end = text.find("{"), text.rfind("}")
    try:
        return OutReview.model_validate_json(text[start : end + 1] if 0 <= start < end else text)
    except ValidationError as error:
        problems = [
            f"{'.'.join(_UNSAFE.sub('?', str(part))[:40] for part in e['loc']) or 'the answer'}: {e['msg']}"
            for e in error.errors(include_url=False, include_input=False)
        ]
        more = len(problems) - _MAX_PROBLEMS
        listed = "; ".join(problems[:_MAX_PROBLEMS]) + (f"; and {more} more" if more > 0 else "")
        raise InvalidReviewError(listed) from error


def review_with_retry(ask: Callable[[Retry | None], str]) -> ReviewResult:
    """Ask, check the answer, and ask once more with what was wrong; then give up with a clear error."""
    answer = ask(None)
    try:
        return read_review(answer).to_result()
    except InvalidReviewError as first:
        note = (
            f"That answer is not a valid review: {first}. Answer again with only the corrected JSON object."
        )
        answer = ask((answer, note))
    try:
        return read_review(answer).to_result()
    except InvalidReviewError as second:
        raise ReviewError(
            f"the model returned output that is not a valid review after one retry: {second}"
        ) from second


def added(earlier: Usage | None, tokens_in: int, tokens_out: int) -> Usage:
    """Usage over several calls of one review: a retry is billed too."""
    if earlier is None:
        return Usage(tokens_in, tokens_out)
    return Usage(earlier.input_tokens + tokens_in, earlier.output_tokens + tokens_out)
