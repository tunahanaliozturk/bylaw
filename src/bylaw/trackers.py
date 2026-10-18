"""Work items in Jira, Azure Boards and Linear as requirements (ADR 0014).

Each tracker is an opt-in in the base branch `.bylaw.toml` with an allow list, and only a reference to an
allowed project or team is read: tracker text can end up in a public comment, as issue text can (ADR 0007).
"""

import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal

from bylaw.config import Config

Tracker = Literal["jira", "azure_boards", "linear"]

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
