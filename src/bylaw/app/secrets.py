"""Model keys and tracker tokens per installation, from the environment or a mounted directory (ADR 0017).

There is no database: a store reads what the operator put in place when it is asked, so a rotated key
takes effect on the next review without a restart. Values are never logged or shown in a repr.
"""

from collections.abc import Mapping
from pathlib import Path
from typing import Protocol

# The variables bylaw itself reads (engine.py, trackers.py). Nothing else is taken from a store.
NAMES = (
    "ANTHROPIC_API_KEY",
    "OPENAI_API_KEY",
    "BYLAW_API_KEY",
    "JIRA_EMAIL",
    "JIRA_API_TOKEN",
    # Where the tracker tokens may go. They serve every repository of the installation, so the operator
    # pins the site and a repository's .bylaw.toml cannot point them elsewhere (trackers.SITES).
    "JIRA_URL",
    "AZURE_DEVOPS_TOKEN",
    "AZURE_DEVOPS_ORGANIZATION",
    "LINEAR_API_KEY",
)


class SecretStore(Protocol):
    def secrets(self, installation_id: int) -> dict[str, str]:
        """The installation's secrets by the name bylaw reads them under, such as ANTHROPIC_API_KEY."""
        ...


class EnvSecrets:
    """`BYLAW_INSTALLATION_<id>_<NAME>`, such as `BYLAW_INSTALLATION_123_ANTHROPIC_API_KEY`."""

    def __init__(self, environ: Mapping[str, str]) -> None:
        self._environ = environ

    def __repr__(self) -> str:
        return "EnvSecrets()"

    def secrets(self, installation_id: int) -> dict[str, str]:
        prefix = f"BYLAW_INSTALLATION_{installation_id}_"
        return {name: value for name in NAMES if (value := self._environ.get(prefix + name))}


class DirectorySecrets:
    """`<root>/<id>/<NAME>`, one file per secret, as Docker and Kubernetes mount secrets."""

    def __init__(self, root: Path) -> None:
        self._root = root

    def __repr__(self) -> str:
        return f"DirectorySecrets({str(self._root)!r})"

    def secrets(self, installation_id: int) -> dict[str, str]:
        folder = self._root / str(installation_id)
        found: dict[str, str] = {}
        for name in NAMES:
            path = folder / name
            if path.is_file() and (value := path.read_text(encoding="utf-8").strip()):
                found[name] = value
        return found
