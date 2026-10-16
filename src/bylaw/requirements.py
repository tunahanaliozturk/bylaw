"""Finds the requirements a change claims to implement and extracts their acceptance criteria (ADR 0003)."""

import re
from collections.abc import Iterable, Sequence
from pathlib import PurePosixPath
from urllib.parse import unquote

from bylaw.model import ChangedFile, Criterion, Requirement
from bylaw.source import ChangeInfo, IssueRef, RepoSource

_ISSUE_REF = re.compile(
    r"\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?):?\s+"
    r"(?:https://github\.com/(?P<url_repo>[\w.-]+/[\w.-]+)/issues/|(?P<repo>[\w.-]+/[\w.-]+)?#)"
    r"(?P<number>\d+)\b",
    re.IGNORECASE,
)
_MD_LINK = re.compile(r"\]\((?P<target>[^)\s]+?\.md)(?:#[^)\s]*)?\)")
_BLOB_URL = re.compile(
    r"https://github\.com/(?P<repo>[\w.-]+/[\w.-]+)/blob/[^/\s]+/(?P<path>[^)\s#]+?\.md)\b"
)

_TASK = re.compile(r"^\s*[-*+]\s+\[[ xX]\]\s+(?P<text>\S.*)$")
_HEADING = re.compile(r"^(?P<hashes>#{1,6})\s+(?P<title>.+?)\s*#*\s*$")
_LIST_ITEM = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+(?:\[[ xX]\]\s+)?(?P<text>\S.*)$")
_CRITERIA_HEADING = re.compile(r"acceptance criteria|requirements|kabul kriterleri", re.IGNORECASE)
_GHERKIN_START = re.compile(r"^\s*(?:[-*+]\s+)?(?:\*\*)?given\b", re.IGNORECASE)
_GHERKIN_NEXT = re.compile(r"^\s*(?:[-*+]\s+)?(?:\*\*)?(?:when|then|and|but)\b", re.IGNORECASE)


def parse_issue_refs(texts: Iterable[str], default_repo: str | None) -> tuple[IssueRef, ...]:
    refs: list[IssueRef] = []
    for text in texts:
        for match in _ISSUE_REF.finditer(text):
            full = match["url_repo"] or match["repo"] or default_repo
            if full is None:
                continue
            owner, _, name = full.lower().partition("/")
            # Text from a pull request is untrusted: "fixes ../..#5" must not become a path into the API.
            if {owner, name} & {"", ".", ".."}:
                continue
            refs.append(IssueRef(owner, name, int(match["number"])))
    return tuple(dict.fromkeys(refs))


def spec_paths(
    changed: Sequence[ChangedFile], body: str, globs: Sequence[str], repo: str | None
) -> tuple[str, ...]:
    candidates = [
        f.path
        for f in changed
        if f.status != "removed"
        and f.path.endswith(".md")
        and any(PurePosixPath(f.path).full_match(g) for g in globs)
    ]
    for match in _BLOB_URL.finditer(body):
        if repo is not None and match["repo"].lower() == repo.lower():
            candidates.append(unquote(match["path"]))
    candidates.extend(m["target"] for m in _MD_LINK.finditer(body) if "://" not in m["target"])
    normalised = (_normalise(path) for path in candidates)
    return tuple(dict.fromkeys(path for path in normalised if path is not None))


def extract_criteria(markdown: str) -> tuple[Criterion, ...]:
    texts: list[str] = []
    in_fence = False
    criteria_level: int | None = None
    gherkin: list[str] | None = None
    for line in markdown.splitlines():
        if line.lstrip().startswith(("```", "~~~")):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        if gherkin is not None:
            if _GHERKIN_NEXT.match(line):
                gherkin.append(_clean(line))
                continue
            texts.append(" ".join(gherkin))
            gherkin = None
        if heading := _HEADING.match(line):
            level = len(heading["hashes"])
            if criteria_level is not None and level <= criteria_level:
                criteria_level = None
            if _CRITERIA_HEADING.search(heading["title"]):
                criteria_level = level
        elif _GHERKIN_START.match(line):
            gherkin = [_clean(line)]
        elif task := _TASK.match(line):
            texts.append(task["text"].strip())
        elif criteria_level is not None and (item := _LIST_ITEM.match(line)):
            texts.append(item["text"].strip())
    if gherkin:
        texts.append(" ".join(gherkin))
    unique = dict.fromkeys(texts)
    return tuple(Criterion(key=f"AC-{i}", text=text) for i, text in enumerate(unique, start=1))


def collect_requirements(
    source: RepoSource,
    info: ChangeInfo,
    changed: Sequence[ChangedFile],
    spec_globs: Sequence[str],
    issue_repos: Sequence[str],
) -> tuple[tuple[Requirement, ...], tuple[str, ...]]:
    requirements: list[Requirement] = []
    notes: list[str] = []
    allowed = {repo.lower() for repo in issue_repos}
    if source.repo is not None:
        allowed.add(source.repo.lower())
    keyword_refs = parse_issue_refs([info.body, *info.commit_messages], source.repo)
    for ref in dict.fromkeys([*source.closing_issue_refs(), *keyword_refs]):
        label = ref.label(source.repo)
        if f"{ref.owner}/{ref.repo}" not in allowed:
            # ADR 0007: issue text ends up in a public comment, so another repository needs an opt-in.
            notes.append(
                f"{label} is in another repository; list it under issue_repos in .bylaw.toml to use it."
            )
            continue
        issue = source.read_issue(ref)
        if issue is None:
            notes.append(f"Could not read {label}; it is left out of the requirement check.")
            continue
        requirements.append(_requirement(label, issue.title, issue.body, issue.comments, issue=True))
        if issue.comments_unreadable:
            notes.append(f"{label}: its comments could not be read; only the issue text is used.")
    for path in spec_paths(changed, info.body, spec_globs, source.repo):
        text = source.read_head(path)
        if text is None:
            notes.append(f"Linked spec {path} does not exist at the head commit.")
            continue
        requirements.append(_requirement(path, _title(text, path), text))
    notes.extend(f"{r.source} has no structured acceptance criteria." for r in requirements if not r.criteria)
    return tuple(requirements), tuple(notes)


def _requirement(
    source: str, title: str, text: str, comments: tuple[str, ...] = (), *, issue: bool = False
) -> Requirement:
    # Criteria come from the body only, so their keys stay stable as the discussion grows.
    discussion = "\n\n".join(comments)
    full = f"{text}\n\n## Comments from maintainers\n\n{discussion}" if comments else text
    criteria = extract_criteria(text)
    # Specs are left as written: a prose ADR in the change is context, not a list of things to check.
    inferable = issue and (not criteria or bool(comments))
    return Requirement(source=source, title=title, text=full, criteria=criteria, inferable=inferable)


def _title(markdown: str, fallback: str) -> str:
    for line in markdown.splitlines():
        if heading := _HEADING.match(line):
            return heading["title"]
    return fallback


def _clean(line: str) -> str:
    return line.strip().lstrip("-*+ ").replace("**", "").strip()


def _normalise(path: str) -> str | None:
    parts = PurePosixPath(path.lstrip("/")).parts
    if not parts or ".." in parts:
        return None
    return "/".join(parts)
