"""Optional .bylaw.toml, always read from the base branch so a change cannot loosen its own review."""

import tomllib
from typing import Annotated, Self
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from bylaw.model import Severity

# A Jira project key or a Linear team key: upper case, so `utf-8` in prose never reads as one.
TrackerKey = Annotated[str, Field(pattern=r"^[A-Z][A-Z0-9_]*$")]


class ConfigError(Exception):
    """The configuration file is invalid. The message is safe to print."""


class Budget(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    # Model tokens, input plus output, one pull request may use across all its runs; none means no cap.
    pr_tokens: int | None = Field(default=None, ge=1_000)


class Jira(BaseModel):
    """Jira Cloud. Credentials come from JIRA_EMAIL and JIRA_API_TOKEN, never from this file (ADR 0014)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    url: str
    projects: tuple[TrackerKey, ...] = Field(min_length=1)
    # The custom field that holds acceptance criteria on this site, such as customfield_10042.
    criteria_field: str | None = Field(default=None, pattern=r"^customfield_\d+$")

    @field_validator("url")
    @classmethod
    def _https_site(cls, url: str) -> str:
        parts = urlsplit(url)
        # The API token travels to this host, so it must be HTTPS and nothing but a site address.
        extra = "@" in parts.netloc or parts.query or parts.fragment
        if parts.scheme != "https" or not parts.hostname or extra:
            raise ValueError("must be an https:// site address without credentials, query or fragment")
        return url.rstrip("/")


class AzureBoards(BaseModel):
    """Azure DevOps Services. The token comes from AZURE_DEVOPS_TOKEN (ADR 0014)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    organization: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9-]*$")
    # AB#123 names no project, so the project a work item belongs to is checked after it is read.
    projects: tuple[str, ...] = Field(min_length=1)


class Linear(BaseModel):
    """Linear. The key comes from LINEAR_API_KEY (ADR 0014)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    teams: tuple[TrackerKey, ...] = Field(min_length=1)


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
    # Work item trackers, each an opt-in with an allow list, like issue_repos (ADR 0007, ADR 0014).
    jira: Jira | None = None
    azure_boards: AzureBoards | None = None
    linear: Linear | None = None
    # False keeps work item text out of the public summary: criterion keys and status only (ADR 0014).
    quote_trackers: bool = True

    @model_validator(mode="after")
    def _one_tracker_per_key(self) -> Self:
        # Jira and Linear keys look the same, so a key must say which tracker it belongs to.
        shared = set(self.jira.projects if self.jira else ()) & set(self.linear.teams if self.linear else ())
        if shared:
            raise ValueError(f"{', '.join(sorted(shared))} listed for both Jira and Linear")
        return self


def load_config(text: str | None) -> Config:
    if text is None:
        return Config()
    try:
        return Config.model_validate(tomllib.loads(text))
    except (tomllib.TOMLDecodeError, ValidationError) as error:
        raise ConfigError(f".bylaw.toml on the base branch is invalid: {error}") from error
