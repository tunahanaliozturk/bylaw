"""Learning from what maintainers do with findings (ADR 0022).

When a pull request closes, `bylaw learn` writes what happened to each of its findings to one JSON file
on the `bylaw-outcomes` branch of the same repository. The records feed suppression suggestions and the
per-repository report. Nothing here changes a review: a suggestion is a pull request a maintainer merges
or closes.
"""

import hashlib
import json
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from http import HTTPStatus
from importlib.metadata import version
from pathlib import PurePosixPath
from typing import Literal

from pydantic import BaseModel, ConfigDict, ValidationError

from bylaw.config import ConfigError, Learn, load_config
from bylaw.github import GitHubClient, GitHubError
from bylaw.model import Category, Suppression
from bylaw.plan import OutcomeStatus, close_outcomes
from bylaw.render import code_span, read_state

STORE_BRANCH = "bylaw-outcomes"
SCHEMA_VERSION: Literal[1] = 1
# ponytail: the newest records only, so a report or a suggestion reads a bounded number of files. Older
# pull requests stop counting; a store that outgrows this needs an index file on the branch.
MAX_RECORDS = 500
_BATCH = 100
# ponytail: a cap on suggestion pull requests per closed pull request, so turning learning on in a repository
# with a long history cannot open dozens at once; the rest come on later runs.
MAX_SUGGESTIONS = 3
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
    """Record a closed pull request's outcomes, when `[learn]` on its base branch says so.

    The settings are read from the base branch as it is now, not at the commit the pull request was
    based on: a pull request opened long ago must not record after learning was turned off, nor suggest
    a suppression a maintainer has added since.
    """
    pull = client.pull(repo, number)
    config = load_config(client.file_text(repo, ".bylaw.toml", pull.base.ref))
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
    opened = 0
    for suggestion in suggestions(read_records(client, repo), config.learn, config.suppress):
        if opened == MAX_SUGGESTIONS:
            break
        try:
            url = open_suggestion(client, repo, pull.base.ref, suggestion)
        except GitHubError as error:
            if error.status not in _WRITE_REFUSED:
                raise
            raise GitHubError(
                f"{error} Opening a suggestion needs `contents: write` and `pull-requests: write`, and the "
                "repository setting that allows GitHub Actions to create pull requests (docs/learning.md).",
                error.status,
            ) from error
        if url:
            opened += 1
            say(f"suggested a suppression of {suggestion.rule} in {url}.")
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


@dataclass(frozen=True, slots=True)
class Suggestion:
    category: str
    rule: str
    # The deepest directory every dismissed finding shares, as a glob; every file when they share none.
    paths: tuple[str, ...]
    # The pull requests that dismissed it, oldest first, and who did in each.
    pull_requests: tuple[int, ...]
    by: tuple[str, ...]
    fixed: int


def tally(records: Iterable[Record]) -> dict[tuple[str, str], tuple[dict[int, tuple[str, str]], int]]:
    """Per category and rule: the pull requests that dismissed it, with who and on which file, and the
    number of pull requests that fixed it. A finding that cites no rule is not counted."""
    dismissed: dict[tuple[str, str], dict[int, tuple[str, str]]] = {}
    fixed: dict[tuple[str, str], set[int]] = {}
    for record in records:
        for f in record.findings:
            if f.rule is None:
                continue
            key = (f.category, f.rule)
            if f.outcome == "fixed":
                fixed.setdefault(key, set()).add(record.pull_request)
            # A dismissal counts only with a login, and never the pull request author's own (ADR 0008).
            elif f.outcome in ("muted", "resolved") and f.by and f.by != record.author:
                dismissed.setdefault(key, {})[record.pull_request] = (f.by, f.file)
    return {key: (by_pull, len(fixed.get(key, ()))) for key, by_pull in dismissed.items()}


def suggestions(records: Iterable[Record], learn: Learn, suppress: Iterable[Suppression]) -> list[Suggestion]:
    """Rules maintainers dismissed in at least `threshold` pull requests, more often than they were fixed.

    Findings are grouped by category and the exact rule they cite: a fingerprint includes the code, so it
    never repeats across pull requests, and a model's message is no stable key. A finding that cites
    nothing is never grouped, and a security finding is never suggested (ADR 0022).
    """
    allowed = set(learn.suggest) - {Category.SECURITY.value}
    suppressed = {s.rule for s in suppress}
    found = []
    for (category, rule), (by_pull, fixes) in tally(records).items():
        if category not in allowed or rule in suppressed:
            continue
        if len(by_pull) < learn.threshold or len(by_pull) <= fixes:
            continue
        numbers = tuple(sorted(by_pull))
        common = _shared_directory(by_pull[n][1] for n in numbers)
        found.append(
            Suggestion(
                category=category,
                rule=rule,
                paths=(f"{'/'.join(common)}/**",) if common else ("**",),
                pull_requests=numbers,
                by=tuple(dict.fromkeys(by_pull[n][0] for n in numbers)),
                fixed=fixes,
            )
        )
    return sorted(found, key=lambda s: (-len(s.pull_requests), s.rule))


def _shared_directory(files: Iterable[str]) -> tuple[str, ...]:
    shared: list[str] = []
    for column in zip(*(PurePosixPath(f).parent.parts for f in files), strict=False):
        if len(set(column)) != 1:
            break
        shared.append(column[0])
    return tuple(shared)


def open_suggestion(client: GitHubClient, repo: str, base: str, suggestion: Suggestion) -> str | None:
    """Open a pull request that adds the suppression to `.bylaw.toml` on `base`; None when one was ever
    opened for this rule before, open or closed: closing it unmerged is the maintainers' answer."""
    key = hashlib.sha256(f"{suggestion.category}\0{suggestion.rule}".encode()).hexdigest()[:12]
    branch = f"bylaw/suppress-{key}"
    head = client.branch_head(repo, base)
    if head is None or client.find_pull(repo, branch):
        return None
    current = client.file_text(repo, ".bylaw.toml", head) or ""
    text = (current.rstrip("\n") + "\n\n" if current.strip() else "") + _suppression_toml(suggestion)
    try:
        load_config(text)
    except ConfigError:
        return None  # never propose a file bylaw itself would refuse, such as a rule past 200 characters
    message = f"bylaw: suggest suppressing {suggestion.rule}"
    client.commit_file(repo, branch, ".bylaw.toml", text, message, start=head)
    try:
        return client.open_pull(
            repo, branch, base, f"Suppress {suggestion.rule}? (suggested by bylaw)", _body(suggestion)
        )
    except GitHubError as error:
        if error.status != HTTPStatus.UNPROCESSABLE_ENTITY:
            raise
        return None  # another pull request closing at the same time opened it first


def _suppression_toml(suggestion: Suggestion) -> str:
    pulls = len(suggestion.pull_requests)
    reason = f"Maintainers dismissed this without a change in {pulls} pull requests."
    return (
        "[[suppress]]\n"
        "# Suggested by bylaw learn (docs/learning.md).\n"
        f"rule = {json.dumps(suggestion.rule)}\n"
        f"paths = [{', '.join(json.dumps(p) for p in suggestion.paths)}]\n"
        f"reason = {json.dumps(reason)}\n"
    )


def _body(suggestion: Suggestion) -> str:
    numbers = [f"#{n}" for n in suggestion.pull_requests]
    listed = ", ".join(numbers[:-1]) + f" and {numbers[-1]}" if len(numbers) > 1 else numbers[0]
    # Logins in code spans, so listing them notifies nobody.
    people = ", ".join(code_span(login) for login in suggestion.by)
    fixed = f"fixed in {suggestion.fixed} pull request(s)" if suggestion.fixed else "never fixed"
    paths = ", ".join(code_span(p) for p in suggestion.paths)
    return (
        f"Maintainers muted or resolved {suggestion.category} findings that cite "
        f"{code_span(suggestion.rule)} without changing the code in {len(numbers)} pull requests: {listed}, "
        f"dismissed by {people}. It was {fixed} in the pull requests bylaw has records of.\n\n"
        f"This pull request adds a suppression for it to `.bylaw.toml`, for {paths}. "
        "Nothing changes until a maintainer merges it, and every summary lists the suppression and what it "
        "hid. Edit the paths or the reason before merging, or close this pull request: bylaw will not "
        "suggest this rule again. If the rule itself is unclear, clarifying it may be the better change.\n\n"
        "bylaw never suggests hiding a security finding, and a suppression never hides one (ADR 0022)."
    )


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
