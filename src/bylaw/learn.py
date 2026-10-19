"""Learning from what maintainers do with findings (ADR 0022).

When a pull request closes, `bylaw learn` writes what happened to each of its findings to one JSON file
on the `bylaw-outcomes` branch of the same repository. The records feed suppression suggestions and the
per-repository report. Nothing here changes a review: a suggestion is a pull request a maintainer merges
or closes.
"""

from collections.abc import Callable, Mapping
from http import HTTPStatus
from importlib.metadata import version
from typing import Literal

from pydantic import BaseModel, ConfigDict, ValidationError

from bylaw.config import load_config
from bylaw.github import GitHubClient, GitHubError, GitHubSource
from bylaw.plan import OutcomeStatus, close_outcomes
from bylaw.render import read_state

STORE_BRANCH = "bylaw-outcomes"
SCHEMA_VERSION: Literal[1] = 1
# ponytail: the newest records only, so a report or a suggestion reads a bounded number of files. Older
# pull requests stop counting; a store that outgrows this needs an index file on the branch.
MAX_RECORDS = 500
_BATCH = 100
_WRITE_REFUSED = frozenset({HTTPStatus.FORBIDDEN, HTTPStatus.NOT_FOUND})

Say = Callable[[str], None]


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")


class StoredFinding(_Frozen):
    fingerprint: str
    category: str
    # The evidence the finding cites, None when it cites nothing.
    rule: str | None
    file: str
    outcome: OutcomeStatus
    # Who muted it or resolved its thread.
    by: str | None = None


class Record(_Frozen):
    """One closed pull request. A field that changes meaning raises the schema version."""

    schema_version: Literal[1] = SCHEMA_VERSION
    pull_request: int
    # The pull request's author: their own mutes never count, and learning checks that again.
    author: str
    merged: bool
    closed_at: str | None
    head_sha: str
    bylaw_version: str = ""
    findings: tuple[StoredFinding, ...]
    # Criteria met, partial, missing and not assessed on the last run.
    criteria: dict[str, int] = {}


def record_path(number: int) -> str:
    return f"pulls/{number}.json"


def learn_from_pull_request(client: GitHubClient, repo: str, number: int, *, say: Say) -> Record | None:
    """Record a closed pull request's outcomes, when `[learn]` on its base branch says so."""
    config = load_config(GitHubSource(client, repo, number).read_base(".bylaw.toml"))
    if not config.learn.enabled:
        say("learning is off ([learn] enabled = false in .bylaw.toml), so nothing was recorded.")
        return None
    summary = client.summary_comment(repo, number)
    if summary is None or not summary.bot:
        # The outcomes say what maintainers did, so they are read only from bylaw's own summary.
        say("no summary written by bylaw's account on this pull request, so there is nothing to record.")
        return None
    state = read_state(summary.body)
    outcomes = close_outcomes(state.outcomes, client.review_threads(repo, number), state.auto_resolved)
    pull = client.pull(repo, number)
    record = Record(
        pull_request=number,
        author=pull.user.login if pull.user else "",
        merged=pull.merged,
        closed_at=pull.closed_at,
        head_sha=pull.head.sha,
        bylaw_version=version("bylaw"),
        findings=tuple(
            StoredFinding(
                fingerprint=fp, category=o.category, rule=o.rule, file=o.file, outcome=o.status, by=o.by
            )
            for fp, o in sorted(outcomes.items())
        ),
        criteria=dict(state.criteria),
    )
    write_record(client, repo, record)
    say(f"recorded {len(record.findings)} outcome(s) of pull request {number} on {STORE_BRANCH}.")
    return record


def write_record(client: GitHubClient, repo: str, record: Record) -> None:
    text = record.model_dump_json(indent=2) + "\n"
    message = f"bylaw: outcomes of pull request {record.pull_request}"
    try:
        client.commit_file(repo, STORE_BRANCH, record_path(record.pull_request), text, message)
    except GitHubError as error:
        if error.status not in _WRITE_REFUSED:
            raise
        raise GitHubError(
            f"{error} Writing the {STORE_BRANCH} branch needs `contents: write` in the workflow's "
            "permissions; a fork's pull_request run never has it, so record from pull_request_target "
            "(docs/learning.md).",
            error.status,
        ) from error


def read_records(client: GitHubClient, repo: str) -> list[Record]:
    """The newest records on the store branch, none when it does not exist yet."""
    try:
        listing = client.tree_shas(repo, STORE_BRANCH)
    except GitHubError as error:
        if error.status in (HTTPStatus.NOT_FOUND, HTTPStatus.CONFLICT):  # no branch, or an empty repository
            return []
        raise
    numbers = sorted(
        (int(path[6:-5]) for path in listing or {} if path.startswith("pulls/") and path[6:-5].isdigit()),
        reverse=True,
    )[:MAX_RECORDS]
    paths = [record_path(n) for n in numbers]
    texts: dict[str, str | None] = {}
    for start in range(0, len(paths), _BATCH):
        texts |= client.files_text(repo, STORE_BRANCH, paths[start : start + _BATCH])
    return parse_records(texts)


def parse_records(texts: Mapping[str, str | None]) -> list[Record]:
    """Records from the store's files; a file that is not one, or has another schema, is left out."""
    records = []
    for text in texts.values():
        if text is None:
            continue
        try:
            records.append(Record.model_validate_json(text))
        except ValidationError:
            continue
    return records
