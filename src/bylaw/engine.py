"""The model-facing review schema and the provider-neutral reviewer interface (ADR 0001)."""

import os
from dataclasses import dataclass
from typing import Protocol

from pydantic import BaseModel, ConfigDict

from bylaw.model import Category, CriterionStatus, ReviewResult, Severity

PROVIDERS = ("anthropic", "openai")
_KEY_VARIABLES = {"anthropic": "ANTHROPIC_API_KEY", "openai": "OPENAI_API_KEY"}


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


def make_reviewer(provider: str, model: str | None, effort: str | None, api_key: str | None) -> Reviewer:
    if provider == "anthropic":
        from bylaw.engine_anthropic import DEFAULT_MODEL, AnthropicReviewer  # noqa: PLC0415 - load one SDK only

        return AnthropicReviewer(model=model or DEFAULT_MODEL, effort=effort or "high", api_key=api_key)
    if provider == "openai":
        if not model:
            raise ReviewError(
                "--model is required with the openai provider; bylaw does not guess model names"
            )
        from bylaw.engine_openai import OpenAIReviewer  # noqa: PLC0415 - load one SDK only

        return OpenAIReviewer(model=model, effort=effort, api_key=api_key)
    raise ReviewError(f"unknown provider {provider!r}; use one of {', '.join(PROVIDERS)}")
