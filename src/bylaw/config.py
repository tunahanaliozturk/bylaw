"""Optional .bylaw.toml, always read from the base branch so a change cannot loosen its own review."""

import tomllib

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from bylaw.model import Severity


class ConfigError(Exception):
    """The configuration file is invalid. The message is safe to print."""


class Budget(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    # Model tokens, input plus output, one pull request may use across all its runs; none means no cap.
    pr_tokens: int | None = Field(default=None, ge=1_000)


class Config(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    spec_globs: tuple[str, ...] = ("docs/specs/**", "docs/adr/**", "**/REQUIREMENTS.md")
    severity_threshold: Severity = Severity.MEDIUM
    max_comments: int = Field(default=15, ge=0, le=50)
    issue_repos: tuple[str, ...] = ()
    # Model input, in tokens. Fits every supported model's context with room for the answer.
    input_token_budget: int = Field(default=300_000, ge=10_000, le=900_000)
    # On a new push, send the model only the files whose change differs from the last run (ADR 0012).
    incremental: bool = True
    budget: Budget = Budget()


def load_config(text: str | None) -> Config:
    if text is None:
        return Config()
    try:
        return Config.model_validate(tomllib.loads(text))
    except (tomllib.TOMLDecodeError, ValidationError) as error:
        raise ConfigError(f".bylaw.toml on the base branch is invalid: {error}") from error
