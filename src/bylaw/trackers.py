"""Work items in Jira, Azure Boards and Linear as requirements (ADR 0014).

Each tracker is an opt-in in the base branch `.bylaw.toml` with an allow list, and only a reference to an
allowed project or team is read: tracker text can end up in a public comment, as issue text can (ADR 0007).
"""

import re
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Any, Literal

import httpx

from bylaw.config import AzureBoards, Config, Jira, Linear
from bylaw.model import Requirement
from bylaw.requirements import extract_criteria

Tracker = Literal["jira", "azure_boards", "linear"]
# A pull request's text decides how many calls bylaw makes with the tracker token, so it is capped.
MAX_WORK_ITEMS = 10
_TIMEOUT = 20.0
_NAMES: dict[Tracker, str] = {"jira": "Jira", "azure_boards": "Azure Boards", "linear": "Linear"}
# Tokens come from the environment only, never from .bylaw.toml (ADR 0014).
CREDENTIALS: dict[Tracker, tuple[str, ...]] = {
    "jira": ("JIRA_EMAIL", "JIRA_API_TOKEN"),
    "azure_boards": ("AZURE_DEVOPS_TOKEN",),
    "linear": ("LINEAR_API_KEY",),
}

# PROJ-123 (Jira) and ENG-123 (Linear) share a shape; the allow lists decide which one a key is.
_KEY_REF = re.compile(r"\b(?P<key>[A-Z][A-Z0-9_]*)-(?P<number>[1-9]\d{0,9})\b")
# The mention Azure Boards itself links from GitHub:
# https://learn.microsoft.com/en-us/azure/devops/boards/github/link-to-from-github
_AB_REF = re.compile(r"\bAB#(?P<number>[1-9]\d{0,9})\b")


@dataclass(frozen=True, slots=True)
class WorkItemRef:
    tracker: Tracker
    key: str


def parse_work_item_refs(texts: Iterable[str], config: Config) -> tuple[WorkItemRef, ...]:
    jira = frozenset(config.jira.projects if config.jira else ())
    linear = frozenset(config.linear.teams if config.linear else ())
    refs: list[WorkItemRef] = []
    for text in texts:
        found: list[tuple[int, WorkItemRef]] = []
        for match in _KEY_REF.finditer(text):
            if match["key"] in jira:
                found.append((match.start(), WorkItemRef("jira", match[0])))
            elif match["key"] in linear:
                found.append((match.start(), WorkItemRef("linear", match[0])))
        if config.azure_boards is not None:
            found.extend(
                (m.start(), WorkItemRef("azure_boards", f"AB#{m['number']}")) for m in _AB_REF.finditer(text)
            )
        refs.extend(ref for _, ref in sorted(found, key=lambda pair: pair[0]))
    return tuple(dict.fromkeys(refs))


@dataclass(frozen=True, slots=True)
class WorkItem:
    title: str
    # Markdown, so the criteria extraction that reads issues reads work items too.
    text: str


class _UnreadableError(Exception):
    """A work item could not be used. The message is a note safe to publish: no token, no tracker text."""


Reader = Callable[[httpx.Client, str], WorkItem]
ClientFactory = Callable[[list[str]], httpx.Client]


def read_work_items(
    texts: Iterable[str], config: Config, env: Mapping[str, str], *, author_trusted: bool = True
) -> tuple[tuple[Requirement, ...], tuple[str, ...]]:
    """Requirements from the work items the texts reference, and notes on the ones left out."""
    refs = parse_work_item_refs(texts, config)
    if refs and not author_trusted and not config.trackers_for_all_authors:
        # The author decides which keys a pull request names; only a trusted one may spend the token.
        named = ", ".join(ref.key for ref in refs[:MAX_WORK_ITEMS])
        was = "was" if len(refs) == 1 else "were"
        return (), (
            f"{named} {was} not read: the pull request author is not an owner, member or collaborator. "
            "trackers_for_all_authors = true in .bylaw.toml reads work items for every author.",
        )
    notes: list[str] = []
    if len(refs) > MAX_WORK_ITEMS:
        left_out = ", ".join(ref.key for ref in refs[MAX_WORK_ITEMS:])
        notes.append(
            f"{len(refs)} work items are referenced; only the first {MAX_WORK_ITEMS} are read. "
            f"Left out: {left_out}."
        )
        refs = refs[:MAX_WORK_ITEMS]
    requirements: list[Requirement] = []
    for tracker, (reader, client) in _readers(config).items():
        keys = [ref.key for ref in refs if ref.tracker == tracker]
        if not keys:
            continue
        names = CREDENTIALS[tracker]
        secrets = [env.get(name, "") for name in names]
        if not all(secrets):
            verb = "are" if len(names) > 1 else "is"
            was = "was" if len(keys) == 1 else "were"
            notes.append(
                f"{' and '.join(names)} {verb} not set, so {', '.join(keys)} {was} not read "
                f"from {_NAMES[tracker]}."
            )
            continue
        with client(secrets) as http:
            for key in keys:
                try:
                    item = reader(http, key)
                except _UnreadableError as error:
                    notes.append(str(error))
                    continue
                criteria = extract_criteria(item.text)
                # ADR 0011: a work item written as prose gets inferred criteria, as an issue does.
                requirements.append(
                    Requirement(
                        source=key,
                        title=item.title,
                        text=item.text,
                        criteria=criteria,
                        inferable=not criteria,
                        quoted=config.quote_trackers,
                    )
                )
    notes.extend(f"{r.source} has no structured acceptance criteria." for r in requirements if not r.criteria)
    return tuple(requirements), tuple(notes)


def _readers(config: Config) -> dict[Tracker, tuple[Reader, ClientFactory]]:
    readers: dict[Tracker, tuple[Reader, ClientFactory]] = {}
    if (jira := config.jira) is not None:
        # Basic auth with the account email and an API token:
        # https://developer.atlassian.com/cloud/jira/platform/basic-auth-for-rest-apis/
        readers["jira"] = (
            lambda http, key: _read_jira(http, jira, key),
            lambda secrets: _client(auth=httpx.BasicAuth(secrets[0], secrets[1])),
        )
    if (boards := config.azure_boards) is not None:
        # A personal access token as Basic auth with an empty user name:
        # https://learn.microsoft.com/en-us/azure/devops/organizations/accounts/use-personal-access-tokens-to-authenticate
        readers["azure_boards"] = (
            lambda http, key: _read_azure_boards(http, boards, key),
            lambda secrets: _client(auth=httpx.BasicAuth("", secrets[0])),
        )
    if (linear := config.linear) is not None:
        # A personal API key goes in the Authorization header as it is: https://linear.app/developers/graphql
        readers["linear"] = (
            lambda http, key: _read_linear(http, linear, key),
            lambda secrets: _client(headers={"Authorization": secrets[0]}),
        )
    return readers


def _client(*, auth: httpx.Auth | None = None, headers: Mapping[str, str] | None = None) -> httpx.Client:
    # No redirects: one could carry the credentials to another host.
    return httpx.Client(
        auth=auth,
        headers={"Accept": "application/json", "User-Agent": "bylaw", **(headers or {})},
        timeout=_TIMEOUT,
        follow_redirects=False,
    )


def _fetch(http: httpx.Client, key: str, tracker: Tracker, request: httpx.Request) -> dict[str, Any]:
    where = f"Could not read {key} from {_NAMES[tracker]}"
    after = "it is left out of the requirement check."
    try:
        response = http.send(request)
    except httpx.HTTPError:
        # The exception text is left out: the note does not need it, and it may name more than it should.
        raise _UnreadableError(f"{where} (network error); {after}") from None
    if response.is_redirect:
        raise _UnreadableError(f"{where} (a redirect, which bylaw does not follow with credentials); {after}")
    if response.status_code != httpx.codes.OK:
        raise _UnreadableError(f"{where} (HTTP {response.status_code}); {after}")
    try:
        data = response.json()
    except ValueError:
        data = None
    if not isinstance(data, dict):
        raise _UnreadableError(f"{where} (the answer was not a JSON object); {after}")
    return data


def _read_jira(http: httpx.Client, jira: Jira, key: str) -> WorkItem:
    # Get issue, Jira Cloud REST v3:
    # https://developer.atlassian.com/cloud/jira/platform/rest/v3/api-group-issues/#api-rest-api-3-issue-issueidorkey-get
    fields = ["summary", "description", *([jira.criteria_field] if jira.criteria_field else [])]
    request = http.build_request(
        "GET", f"{jira.url}/rest/api/3/issue/{key}", params={"fields": ",".join(fields)}
    )
    data = _fetch(http, key, "jira", request)
    # Jira answers a moved issue's old key with the issue under its new key, not with a redirect, so the
    # project is checked on the answer as well as on the reference.
    found = data.get("key")
    if not isinstance(found, str) or found.partition("-")[0] not in jira.projects:
        raise _UnreadableError(
            f"{key} has moved to a Jira project that is not listed under [jira] projects; it is left out."
        )
    values = _mapping(data.get("fields"))
    criteria = _rich_text(values.get(jira.criteria_field)) if jira.criteria_field else ""
    title = values.get("summary")
    return WorkItem(
        title=title if isinstance(title, str) and title else key,
        text=with_criteria(_rich_text(values.get("description")), criteria),
    )


def _read_azure_boards(http: httpx.Client, boards: AzureBoards, key: str) -> WorkItem:
    # Work Items - Get Work Item, REST 7.1; the project is optional in the path because ids are unique
    # across an organisation's projects:
    # https://learn.microsoft.com/en-us/rest/api/azure/devops/wit/work-items/get-work-item?view=azure-devops-rest-7.1
    # No `fields` list: asking for a field a process does not define is an error, and all fields are small.
    number = key.removeprefix("AB#")
    url = f"https://dev.azure.com/{boards.organization}/_apis/wit/workitems/{number}"
    data = _fetch(http, key, "azure_boards", http.build_request("GET", url, params={"api-version": "7.1"}))
    # Field reference names:
    # https://learn.microsoft.com/en-us/azure/devops/boards/queries/titles-ids-descriptions?view=azure-devops
    values = _mapping(data.get("fields"))
    project = values.get("System.TeamProject")
    # AB#123 names no project, so the allow list is checked on the answer; project names ignore case.
    allowed = {name.casefold() for name in boards.projects}
    if not isinstance(project, str) or project.casefold() not in allowed:
        raise _UnreadableError(
            f"{key} is in an Azure DevOps project that is not listed under [azure_boards] projects; "
            "it is left out."
        )
    title = values.get("System.Title")
    return WorkItem(
        title=title if isinstance(title, str) and title else key,
        text=with_criteria(
            html_markdown(_string(values.get("System.Description"))),
            html_markdown(_string(values.get("Microsoft.VSTS.Common.AcceptanceCriteria"))),
        ),
    )


_LINEAR_URL = "https://api.linear.app/graphql"
# `issue(id:)` takes an identifier such as ENG-123 (https://linear.app/developers/graphql); the field
# names are those of the Issue type in Linear's published schema,
# https://github.com/linear/linear/blob/master/packages/sdk/src/schema.graphql
_LINEAR_QUERY = "query($id: String!) { issue(id: $id) { identifier title description team { key } } }"


def _read_linear(http: httpx.Client, linear: Linear, key: str) -> WorkItem:
    request = http.build_request("POST", _LINEAR_URL, json={"query": _LINEAR_QUERY, "variables": {"id": key}})
    data = _fetch(http, key, "linear", request)
    issue = _mapping(_mapping(data.get("data")).get("issue"))
    # GraphQL reports errors with status 200. Their text is not passed on: it is the API's, not bylaw's.
    if data.get("errors") or not issue:
        raise _UnreadableError(
            f"Could not read {key} from Linear (the API answered with an error); "
            "it is left out of the requirement check."
        )
    # An issue moved to another team answers to its old identifier too, so the team is checked on the answer.
    if _mapping(issue.get("team")).get("key") not in linear.teams:
        raise _UnreadableError(
            f"{key} has moved to a Linear team that is not listed under [linear] teams; it is left out."
        )
    title = issue.get("title")
    # The description is Markdown already.
    return WorkItem(
        title=title if isinstance(title, str) and title else key, text=_string(issue.get("description"))
    )


def _string(value: object) -> str:
    return value if isinstance(value, str) else ""


_HTML_BLOCKS = frozenset({"p", "div", "br", "tr", "table", "blockquote", "pre", "hr"})
_HTML_SKIPPED = frozenset({"script", "style"})
_HTML_HEADINGS = {f"h{level}": level for level in range(1, 7)}
_EMPTY_LINE = re.compile(r"^\s*(?:[-*]|\d+\.|#+)?\s*$")


class _HtmlText(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.lines = [""]
        self._lists: list[tuple[str, int]] = []  # open lists: tag and items so far
        self._skipping = 0

    def _break(self) -> None:
        # A line holding only a list marker or heading hashes is where the next text belongs.
        if not _EMPTY_LINE.match(self.lines[-1]):
            self.lines.append("")

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:  # noqa: ARG002
        if tag in _HTML_SKIPPED:
            self._skipping += 1
        elif tag in {"ul", "ol"}:
            self._break()
            self._lists.append((tag, 0))
        elif tag == "li":
            self._break()
            kind, count = self._lists[-1] if self._lists else ("ul", 0)
            if self._lists:
                self._lists[-1] = (kind, count + 1)
            marker = f"{count + 1}. " if kind == "ol" else "- "
            self.lines[-1] = "  " * max(len(self._lists) - 1, 0) + marker
        elif tag in _HTML_HEADINGS:
            self._break()
            self.lines[-1] = "#" * _HTML_HEADINGS[tag] + " "
        elif tag in _HTML_BLOCKS:
            self._break()

    def handle_endtag(self, tag: str) -> None:
        if tag in _HTML_SKIPPED:
            self._skipping = max(self._skipping - 1, 0)
        elif tag in {"ul", "ol"}:
            if self._lists:
                self._lists.pop()
            self._break()
        elif tag == "li" or tag in _HTML_HEADINGS or tag in _HTML_BLOCKS:
            self._break()

    def handle_data(self, data: str) -> None:
        if not self._skipping:
            # Whitespace in HTML is not layout; a non-breaking space counts as one too.
            self.lines[-1] += re.sub(r"\s+", " ", data.replace("\xa0", " "))


def html_markdown(html: str) -> str:
    """Markdown for the HTML of an Azure DevOps rich text field: lists and headings keep their shape."""
    parser = _HtmlText()
    parser.feed(html)
    parser.close()
    # A nested list item keeps its indent; any other line loses the space collapsed whitespace left.
    kept = [line.rstrip() if _LIST_LINE.match(line) else line.strip() for line in parser.lines]
    return "\n".join(line for line in kept if not _EMPTY_LINE.match(line))


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, dict) else {}


def _rich_text(value: object) -> str:
    """Jira v3 sends rich text as an Atlassian Document Format tree; a plain text field is a string."""
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return adf_markdown(value)
    return ""


_LIST_LINE = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s")


def with_criteria(text: str, criteria: str) -> str:
    """The text, with a tracker's own acceptance criteria field added as a section the extraction reads.

    Every line of that field counts as a criterion, so a field written as plain lines is still a checklist.
    """
    lines = [
        line if _LIST_LINE.match(line) else f"- {line.lstrip('# ').strip()}"
        for line in criteria.splitlines()
        if line.strip() and not line.lstrip().startswith(("```", "~~~"))
    ]
    if not lines:
        return text
    return f"{text}\n\n## Acceptance criteria\n\n" + "\n".join(lines)


# Atlassian Document Format: https://developer.atlassian.com/cloud/jira/platform/apis/document/structure/
_ADF_BLOCKS = frozenset(
    {
        "paragraph",
        "heading",
        "bulletList",
        "orderedList",
        "taskList",
        "decisionList",
        "listItem",
        "taskItem",
        "decisionItem",
        "codeBlock",
        "blockquote",
        "panel",
        "expand",
        "nestedExpand",
        "table",
        "tableRow",
        "tableHeader",
        "tableCell",
        "rule",
        "mediaGroup",
        "mediaSingle",
    }
)
_ADF_LISTS = frozenset({"bulletList", "orderedList", "taskList", "decisionList"})


def adf_markdown(doc: Mapping[str, Any]) -> str:
    """Markdown for an Atlassian Document Format tree: headings, lists and action items keep their shape."""
    blocks = [_adf_block(child, "") for child in _children(doc)]
    return "\n\n".join("\n".join(lines) for lines in blocks if lines)


def _children(node: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    content = node.get("content")
    return [child for child in content if isinstance(child, dict)] if isinstance(content, list) else []


def _adf_block(node: Mapping[str, Any], indent: str) -> list[str]:
    kind = node.get("type")
    if kind == "heading":
        level = _mapping(node.get("attrs")).get("level")
        hashes = "#" * min(max(level, 1), 6) if isinstance(level, int) else "#"
        return [f"{indent}{hashes} {_adf_inline(node)}"]
    if kind == "paragraph":
        return [f"{indent}{line}" for line in _adf_inline(node).splitlines() if line.strip()]
    if kind == "codeBlock":
        # Fenced, so a checklist inside a code sample is not read as criteria.
        return [
            f"{indent}```",
            *(f"{indent}{line}" for line in _adf_inline(node).splitlines()),
            f"{indent}```",
        ]
    if kind in _ADF_LISTS:
        lines: list[str] = []
        for number, item in enumerate(_children(node), start=1):
            lines.extend(_adf_item(item, _marker(kind, number, item), indent))
        return lines
    if kind == "blockquote":
        return [f"{indent}> {line.strip()}" for line in _adf_content(node, indent)]
    return _adf_content(node, indent)


def _marker(kind: object, number: int, item: Mapping[str, Any]) -> str:
    if kind == "orderedList":
        return f"{number}. "
    if kind == "taskList":
        return "- [x] " if _mapping(item.get("attrs")).get("state") == "DONE" else "- [ ] "
    return "- "


def _adf_item(item: Mapping[str, Any], marker: str, indent: str) -> list[str]:
    inner = indent + "  "
    lines = _adf_content(item, inner)
    if not lines:
        return []
    return [f"{indent}{marker}{lines[0].removeprefix(inner)}", *lines[1:]]


def _adf_content(node: Mapping[str, Any], indent: str) -> list[str]:
    """Block children in order; a run of inline children (an action item's text) is one paragraph."""
    lines: list[str] = []
    inline: list[Mapping[str, Any]] = []
    for child in [*_children(node), None]:
        if child is not None and child.get("type") not in _ADF_BLOCKS:
            inline.append(child)
            continue
        if inline:
            lines.extend(_adf_block({"type": "paragraph", "content": inline}, indent))
            inline = []
        if child is not None:
            lines.extend(_adf_block(child, indent))
    return lines


def _adf_inline(node: Mapping[str, Any]) -> str:
    parts: list[str] = []
    for child in _children(node):
        kind = child.get("type")
        attrs = _mapping(child.get("attrs"))
        if kind == "text":
            parts.append(str(child.get("text", "")))
        elif kind == "hardBreak":
            parts.append("\n")
        elif kind in {"mention", "emoji", "status", "date"}:
            parts.append(str(attrs.get("text") or attrs.get("shortName") or ""))
        elif kind in {"inlineCard", "blockCard"}:
            parts.append(str(attrs.get("url", "")))
        else:
            parts.append(_adf_inline(child))
    return "".join(parts)
