"""The model-facing review schema and the provider-neutral reviewer interface (ADR 0001)."""

import ipaddress
import json
import os
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import urlsplit

import httpx2
from pydantic import BaseModel, ConfigDict, ValidationError

from bylaw.model import Category, CriterionStatus, ReviewResult, Severity

PROVIDERS = ("anthropic", "openai", "bedrock", "vertex", "foundry", "azure-openai", "openai-compatible")
_KEY_VARIABLES = {
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
    "openai-compatible": "BYLAW_BASE_URL_KEY",
}
# BYLAW_API_KEY, the Action's api-key input, is for these two only: a server at any base URL, or a cloud,
# must never get a key that was meant for Anthropic or OpenAI.
_SHARED_KEY = frozenset({"anthropic", "openai"})
# A local server needs no key, and a cloud provider authenticates through its own credential chain (an AWS
# profile or role, for one), which bylaw cannot see without calling it. Neither stops the model review.
_NO_KEY_NEEDED = frozenset({"bedrock", "vertex", "foundry", "azure-openai", "openai-compatible"})
# The scope Microsoft documents for Entra ID tokens to Foundry and Azure OpenAI.
_AZURE_AI_SCOPE = "https://ai.azure.com/.default"


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


_SCHEMA_FIELDS: frozenset[str] = frozenset().union(
    *(model.model_fields for model in (OutReview, OutFinding, OutLocation, OutCriterion, OutScopeCreep))
)


class Reviewer(Protocol):
    def review(self, system: str, user: str) -> ReviewResult: ...


def api_key_for(provider: str, env: Mapping[str, str] | None = None) -> str | None:
    """The key from `env`, the process environment when not given; the GitHub App passes the
    installation's secrets so a server-wide key never reviews for an installation (ADR 0017)."""
    source = os.environ if env is None else env
    # The provider's own variable wins, so a key meant for one provider is never sent to another.
    own = source.get(_KEY_VARIABLES.get(provider, ""))
    if own or provider not in _SHARED_KEY:
        return own or None
    return source.get("BYLAW_API_KEY") or None


def key_variable(provider: str) -> str:
    """The variable that holds the provider's own key, for messages."""
    return _KEY_VARIABLES.get(provider, "BYLAW_API_KEY")


def can_review(provider: str) -> bool:
    """Whether the model review can be tried: a key is set, or the provider does not need one."""
    return provider in _NO_KEY_NEEDED or api_key_for(provider) is not None


def make_reviewer(  # noqa: PLR0911, PLR0913 - a branch per provider; the base URL and client are optional
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
    if provider == "foundry":
        from bylaw.engine_anthropic import foundry_reviewer  # noqa: PLC0415 - load one SDK only

        return foundry_reviewer(model, effort, http_client)
    import openai  # noqa: PLC0415 - load one SDK only

    from bylaw.engine_openai import ChatReviewer, OpenAIReviewer  # noqa: PLC0415

    if provider == "openai":
        client = openai.OpenAI(api_key=api_key, http_client=http_client, max_retries=3)
        return OpenAIReviewer(client=client, model=_named(model, provider), effort=effort)
    if provider == "azure-openai":
        from bylaw.engine_openai import azure_reviewer  # noqa: PLC0415

        return azure_reviewer(_named(model, provider), effort, http_client)
    if provider == "openai-compatible":
        if not base_url:
            raise ReviewError("--base-url is required with the openai-compatible provider")
        if _plain_http_off_machine(base_url):
            # The brief is the pull request's code; across a network it goes encrypted or not at all.
            raise ReviewError("--base-url must use https unless the server is on this machine (localhost)")
        refuse_header_list("OPENAI_CUSTOM_HEADERS", provider)
        # Always a key of its own: left empty, the SDK would read OPENAI_API_KEY and send it to this server.
        local = openai.OpenAI(
            api_key=api_key or "unused", base_url=base_url, http_client=http_client, max_retries=1
        )
        without_openai_ids(local)
        return ChatReviewer(client=local, model=_named(model, provider), effort=effort)
    raise ReviewError(f"unknown provider {provider!r}; use one of {', '.join(PROVIDERS)}")


def entra_token_provider(key_variable: str) -> Callable[[], str]:
    """Microsoft Entra ID tokens from DefaultAzureCredential: az login, a managed identity, workload identity
    or a service principal in AZURE_CLIENT_ID, AZURE_TENANT_ID and AZURE_CLIENT_SECRET."""
    try:
        from azure.identity import DefaultAzureCredential, get_bearer_token_provider  # noqa: PLC0415
    except ImportError as error:
        extra = "install the azure extra for Microsoft Entra ID: pip install 'bylaw[azure]'"
        raise ReviewError(f"set {key_variable}, or {extra}") from error
    return get_bearer_token_provider(DefaultAzureCredential(), _AZURE_AI_SCOPE)


def credential_errors() -> tuple[type[Exception], ...]:
    """What a cloud credential chain raises when it finds nothing or cannot refresh a token: botocore,
    google-auth and azure-identity errors, the SDKs' own credential RuntimeErrors, and an ImportError for a
    missing piece of an extra. Each library is optional, so each is looked up only if it is installed."""
    errors: list[type[Exception]] = [RuntimeError, ImportError]
    try:
        from botocore.exceptions import BotoCoreError  # type: ignore[import-untyped]  # noqa: PLC0415

        errors.append(BotoCoreError)
    except ImportError:
        pass
    try:
        from google.auth.exceptions import GoogleAuthError  # noqa: PLC0415

        errors.append(GoogleAuthError)
    except ImportError:
        pass
    try:
        # CredentialUnavailableError is a ClientAuthenticationError.
        from azure.core.exceptions import ClientAuthenticationError  # noqa: PLC0415

        errors.append(ClientAuthenticationError)
    except ImportError:
        pass
    return tuple(errors)


def refuse_header_list(variable: str, provider: str) -> None:
    """The SDKs add the headers listed in OPENAI_CUSTOM_HEADERS or ANTHROPIC_CUSTOM_HEADERS to every request,
    an Authorization line included; set for the OpenAI or Claude API, they must not reach another provider."""
    if os.environ.get(variable) is not None:
        raise ReviewError(f"{variable} is set; it would send its headers to {provider}, so unset it")


def refuse_empty(*variables: str) -> None:
    """A key variable set to nothing, as a workflow leaves it when the secret it passes does not exist. The
    SDKs would take it as a key and send an empty one instead of using the credential chain."""
    for variable in variables:
        if os.environ.get(variable) == "":
            raise ReviewError(f"{variable} is set but empty; give it a value or unset it")


def without_openai_ids(client: object) -> None:
    """The OpenAI client fills these from OPENAI_ORG_ID and OPENAI_PROJECT_ID, which belong to OpenAI."""
    client.organization = None  # type: ignore[attr-defined]
    client.project = None  # type: ignore[attr-defined]


def _plain_http_off_machine(url: str) -> bool:
    parts = urlsplit(url)
    if parts.scheme != "http":
        return False
    host = parts.hostname or ""
    if host == "localhost":
        return False
    try:
        return not ipaddress.ip_address(host).is_loopback
    except ValueError:  # a name other than localhost
        return True


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
# Reasoning models served locally often write their thinking inline, braces and all.
_THINKING = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
_DECODER = json.JSONDecoder()


def json_instructions() -> str:
    schema = json.dumps(OutReview.model_json_schema(), separators=(",", ":"))
    return (
        "\n\nAnswer with one JSON object and nothing else: no prose before or after it. "
        f"It must follow this JSON schema exactly:\n{schema}"
    )


class InvalidReviewError(Exception):
    """What is wrong with an answer, by field path. It never quotes the answer: that text is the model's."""


def read_review(text: str) -> OutReview:
    """The first JSON object in the answer, after any thinking block, checked against the schema. Prose,
    a code fence or a second object around it does not matter."""
    found: dict[str, object] | None = None
    text = _THINKING.sub("", text)
    # ponytail: a decode attempt at every brace, quadratic in the worst case; answers are a few kilobytes.
    for start in (i for i, char in enumerate(text) if char == "{"):
        try:
            value, _ = _DECODER.raw_decode(text, start)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            found = value
            break
    if found is None:
        raise InvalidReviewError("the answer holds no JSON object")
    try:
        return OutReview.model_validate(found)
    except ValidationError as error:
        problems = [
            f"{_where(e['loc'])}: {e['msg']}" for e in error.errors(include_url=False, include_input=False)
        ]
        more = len(problems) - _MAX_PROBLEMS
        listed = "; ".join(problems[:_MAX_PROBLEMS]) + (f"; and {more} more" if more > 0 else "")
        raise InvalidReviewError(listed) from error


def _where(loc: tuple[int | str, ...]) -> str:
    # Only the schema's own names and list indexes: a field name the model made up is its text, and it would
    # reach the retry and the public note.
    parts = [
        str(part) if isinstance(part, int) else part if part in _SCHEMA_FIELDS else "an unexpected field"
        for part in loc
    ]
    return ".".join(parts) or "the answer"


def review_with_retry(ask: Callable[[Retry | None], str]) -> ReviewResult:
    """Ask, check the answer, and ask once more with what was wrong; then give up with a clear error."""
    answer = _some_text(ask(None))
    try:
        return read_review(answer).to_result()
    except InvalidReviewError as first:
        note = (
            f"That answer is not a valid review: {first}. Answer again with only the corrected JSON object."
        )
        answer = _some_text(ask((answer, note)))
    try:
        return read_review(answer).to_result()
    except InvalidReviewError as second:
        raise ReviewError(
            f"the model returned output that is not a valid review after one retry: {second}"
        ) from second


def _some_text(answer: str) -> str:
    # An empty answer cannot be sent back: an empty assistant turn is a 400 on every API.
    if not answer.strip():
        raise ReviewError("the model declined or returned no review")
    return answer


def added(earlier: Usage | None, tokens_in: int, tokens_out: int) -> Usage:
    """Usage over several calls of one review: a retry is billed too."""
    if earlier is None:
        return Usage(tokens_in, tokens_out)
    return Usage(earlier.input_tokens + tokens_in, earlier.output_tokens + tokens_out)
