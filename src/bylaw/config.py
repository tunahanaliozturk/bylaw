"""Optional .bylaw.toml, always read from the base branch so a change cannot loosen its own review."""

import tomllib

from pydantic import BaseModel, ConfigDict, ValidationError


class ConfigError(Exception):
    """The configuration file is invalid. The message is safe to print."""


class Config(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    spec_globs: tuple[str, ...] = ("docs/specs/**", "docs/adr/**", "**/REQUIREMENTS.md")


def load_config(text: str | None) -> Config:
    if text is None:
        return Config()
    try:
        return Config.model_validate(tomllib.loads(text))
    except (tomllib.TOMLDecodeError, ValidationError) as error:
        raise ConfigError(f".bylaw.toml on the base branch is invalid: {error}") from error
