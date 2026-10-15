from dataclasses import dataclass, field

from bylaw.model import ChangedFile
from bylaw.source import ChangeInfo, Issue, IssueRef


@dataclass
class FakeSource:
    repo: str | None = "octo/app"
    base: dict[str, str] = field(default_factory=dict)
    head: dict[str, str] = field(default_factory=dict)
    files: tuple[ChangedFile, ...] = ()
    title: str = "Add login"
    body: str = ""
    commits: tuple[str, ...] = ()
    closing: tuple[IssueRef, ...] = ()
    issues: dict[IssueRef, Issue] = field(default_factory=dict)

    def info(self) -> ChangeInfo:
        return ChangeInfo("base0", "head0", self.title, self.body, self.commits)

    def changed_files(self) -> tuple[ChangedFile, ...]:
        return self.files

    def read_base(self, path: str) -> str | None:
        return self.base.get(path)

    def read_head(self, path: str) -> str | None:
        return self.head.get(path)

    def closing_issue_refs(self) -> tuple[IssueRef, ...]:
        return self.closing

    def read_issue(self, ref: IssueRef) -> Issue | None:
        return self.issues.get(ref)
