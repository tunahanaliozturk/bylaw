"""Optional .bylaw.toml, always read from the base branch so a change cannot loosen its own review."""

import tomllib
from typing import Annotated, Literal, Self
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from bylaw.compliance import available
from bylaw.model import Severity

# A Jira project key or a Linear team key: upper case, so `utf-8` in prose never reads as one.
TrackerKey = Annotated[str, Field(pattern=r"^[A-Z][A-Z0-9_]*$")]


# Values are left out of validation errors: a token pasted into the file must not reach the Actions log.
_SETTINGS = ConfigDict(frozen=True, extra="forbid", hide_input_in_errors=True)


class ConfigError(Exception):
    """The configuration file is invalid. The message is safe to print."""


class Budget(BaseModel):
    model_config = _SETTINGS

    # Model tokens, input plus output, one pull request may use across all its runs; none means no cap.
    pr_tokens: int | None = Field(default=None, ge=1_000)


class Jira(BaseModel):
    """Jira Cloud. Credentials come from JIRA_EMAIL and JIRA_API_TOKEN, never from this file (ADR 0014)."""

    model_config = _SETTINGS

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

    model_config = _SETTINGS

    organization: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9-]*$")
    # AB#123 names no project, so the project a work item belongs to is checked after it is read.
    projects: tuple[str, ...] = Field(min_length=1)


class Linear(BaseModel):
    """Linear. The key comes from LINEAR_API_KEY (ADR 0014)."""

    model_config = _SETTINGS

    teams: tuple[TrackerKey, ...] = Field(min_length=1)


class App(BaseModel):
    """Settings only the GitHub App reads (ADR 0017). The Action leaves fork pull requests to its workflow."""

    model_config = _SETTINGS

    # Which pull requests the installation's model key reviews: "trusted" is a branch of this repository
    # by an owner, member or collaborator; "all" is every pull request, forks included.
    model_review: Literal["trusted", "all"] = "trusted"
    # A label a maintainer adds to one pull request to give it the model review anyway.
    model_review_label: str | None = Field(default=None, min_length=1, max_length=50)


# The `.bylaw.toml` versions this bylaw reads (ADR 0023). A file without `version` is version 1.
CONFIG_VERSIONS = (1,)


class Learn(BaseModel):
    """Learning from what maintainers do with findings (ADR 0022). Off unless a maintainer turns it on."""

    model_config = _SETTINGS

    # Record each closed pull request's outcomes on the `bylaw-outcomes` branch and suggest suppressions.
    enabled: bool = False
    # Distinct pull requests in which maintainers muted, or resolved without a change, the same kind of
    # finding before bylaw suggests a suppression for it.
    threshold: int = Field(default=3, ge=2, le=100)
    # The categories a suggestion may cover. Security is not a choice: it is never suggested.
    suggest: tuple[Literal["rule", "bug"], ...] = ("rule",)


class Config(BaseModel):
    model_config = _SETTINGS

    version: int = 1
    spec_globs: tuple[str, ...] = ("docs/specs/**", "**/REQUIREMENTS.md")
    # Where the ADRs live. Accepted ones are decisions read from the base branch, never specs (ADR 0016).
    adr_globs: tuple[str, ...] = ("docs/adr/**", "doc/adr/**", "docs/decisions/**")
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
    # Work items are read only for pull requests by owners, members and collaborators unless this is set:
    # anyone else could name allowed keys to pull their text into a comment (ADR 0014).
    trackers_for_all_authors: bool = False
    app: App = App()
    # Compliance profiles shipped with bylaw, such as "iso27001" (ADR 0021).
    profiles: tuple[str, ...] = ()
    learn: Learn = Learn()

    @field_validator("version")
    @classmethod
    def _readable(cls, version: int) -> int:
        if version not in CONFIG_VERSIONS:
            known = ", ".join(str(v) for v in CONFIG_VERSIONS)
            raise ValueError(f"the file says version {version}, and this bylaw reads version {known}")
        return version

    @field_validator("profiles")
    @classmethod
    def _known_profiles(cls, names: tuple[str, ...]) -> tuple[str, ...]:
        # A typo must fail loudly: a team relying on a profile must never be reviewed without it.
        if any(name not in available() for name in names):
            raise ValueError(f"unknown compliance profile; bylaw has {', '.join(available())}")
        return tuple(dict.fromkeys(names))

    @model_validator(mode="after")
    def _one_tracker_per_key(self) -> Self:
        # Jira and Linear keys look the same, so a key must say which tracker it belongs to.
        shared = set(self.jira.projects if self.jira else ()) & set(self.linear.teams if self.linear else ())
        if shared:
            raise ValueError(f"{', '.join(sorted(shared))} listed for both Jira and Linear")
        return self


_BASE = ".bylaw.toml on the base branch"
_DEFAULTS = "The organisation's .bylaw.toml in its .github repository"


def load_config(text: str | None, defaults: str | None = None) -> Config:
    """The base branch's settings over the organisation's `defaults` (GitHub App, ADR 0017).

    A key the repository sets wins. A table such as `[jira]` counts as one key and is replaced whole, so a
    tracker site from one file never pairs with an allow list from the other. `profiles` is the exception:
    the repository's add to the organisation's, so a repository cannot drop one (ADR 0021).
    """
    org = _parse(defaults, _DEFAULTS)
    if org:
        _validate(org, _DEFAULTS)
    repo = _parse(text, _BASE)
    merged = {**org, **repo}
    floor, added = org.get("profiles"), repo.get("profiles")
    if isinstance(floor, list) and isinstance(added, list):
        merged["profiles"] = [*floor, *added]
    return _validate(merged, _BASE)


def _parse(text: str | None, where: str) -> dict[str, object]:
    if text is None:
        return {}
    try:
        return tomllib.loads(text)
    except tomllib.TOMLDecodeError as error:
        raise ConfigError(f"{where} is invalid: {error}") from None


def _validate(data: dict[str, object], where: str) -> Config:
    try:
        return Config.model_validate(data)
    except ValidationError as error:
        message = f"{where} is invalid: {error}"
        if any(problem["type"] == "extra_forbidden" for problem in error.errors(include_input=False)):
            # An unknown key may be a token put in the wrong place; its value is not shown, but it is public.
            message += (
                " If an unknown setting holds a token or key, remove it and rotate that token: tracker "
                "tokens are read from the environment only."
            )
        raise ConfigError(message) from None


# Keys that still work but go in the next major release, each with what to use instead. A key stays here,
# working, for at least one minor release before it is removed (docs/compatibility.md). A key inside a
# table is written with a dot, such as "app.model_review".
DEPRECATED_KEYS: dict[str, str] = {}
DEPRECATED = "Deprecated: "


def deprecations(config: Config) -> tuple[str, ...]:
    """A note for each deprecated key the configuration sets, for the summary and standard error."""
    return tuple(
        f"{DEPRECATED}`{key}` in .bylaw.toml still works, but goes in the next major release. {advice}"
        for key, advice in DEPRECATED_KEYS.items()
        if _sets(config, key)
    )


def _sets(model: BaseModel, key: str) -> bool:
    head, _, rest = key.partition(".")
    if head not in model.model_fields_set:
        return False
    inner = getattr(model, head)
    return not rest or (isinstance(inner, BaseModel) and _sets(inner, rest))
