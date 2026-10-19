"""RPT-3: `bylaw report` reads the outcome branch and writes the page, and the Action publishes it."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest
import respx
from ruamel.yaml import YAML

from bylaw.cli import main
from bylaw.learn import STORE_BRANCH, Record, StoredFinding, record_path
from tests.integration.fake_github import API, REPO, FakeGitHub

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(autouse=True)
def github_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GITHUB_TOKEN", "t")
    monkeypatch.setenv("GITHUB_API_URL", API)
    monkeypatch.delenv("GITHUB_GRAPHQL_URL", raising=False)


def _report(github: FakeGitHub, out: Path) -> int:
    with respx.mock(assert_all_called=False) as router:
        router.route(host="api.github.test").mock(side_effect=github)
        return main(["report", "--repo", REPO, "--output", str(out)])


def test_the_report_is_written_from_the_records_on_the_outcome_branch(tmp_path: Path) -> None:
    finding = StoredFinding(fingerprint="f", category="rule", rule="ruff:S101", file="a.py", outcome="fixed")
    records = [
        Record(
            pull_request=n,
            author="a",
            merged=True,
            closed_at="2027-08-01T00:00:00Z",
            head_sha="h",
            findings=(finding,),
        )
        for n in (1, 2)
    ]
    github = FakeGitHub()
    github.put_branch(STORE_BRANCH, {record_path(r.pull_request): r.model_dump_json() for r in records})

    assert _report(github, tmp_path / "report") == 0

    page = (tmp_path / "report" / "index.html").read_text(encoding="utf-8")
    assert "2 pull requests closed" in page
    assert "<tr><td>rule</td><td>2</td><td>2</td>" in page
    assert {p.name for p in (tmp_path / "report").iterdir()} >= {"findings-light.png", "findings-dark.png"}


def test_without_an_outcome_branch_the_report_says_nothing_was_recorded(tmp_path: Path) -> None:
    assert _report(FakeGitHub(), tmp_path / "report") == 0

    assert "No pull request has been recorded yet" in (tmp_path / "report" / "index.html").read_text(
        encoding="utf-8"
    )


def _steps() -> dict[str, dict[str, object]]:
    action = YAML(typ="safe").load((ROOT / "action.yml").read_text(encoding="utf-8"))
    return {str(s.get("id") or s.get("uses", "")).partition("@")[0]: s for s in action["runs"]["steps"]}


def test_the_action_writes_the_report_when_a_pull_request_closes_or_runs_without_one() -> None:
    steps = _steps()

    expected = (
        "${{ inputs.report != 'none' && (github.event.action == 'closed' || !github.event.pull_request) }}"
    )
    assert steps["report"]["if"] == expected
    assert steps["review"]["if"] == "${{ github.event.pull_request && github.event.action != 'closed' }}"


@pytest.mark.parametrize(
    ("action", "mode"),
    [
        ("actions/upload-artifact", "artifact"),
        ("actions/upload-pages-artifact", "pages"),
        ("actions/deploy-pages", "pages"),
    ],
)
def test_the_report_is_published_with_official_actions_pinned_by_commit(action: str, mode: str) -> None:
    step = next(
        s
        for s in _steps().values()
        if str(s.get("uses", "")).startswith(f"{action}@") and mode in str(s["if"])
    )

    sha = str(step["uses"]).partition("@")[2].partition(" ")[0]
    assert len(sha) == 40 and all(c in "0123456789abcdef" for c in sha)
    condition = f"steps.report.outputs.dir != '' && inputs.report == '{mode}'"
    # Pages deploys from the default branch only, never from a pull request's run (docs/learning.md).
    if mode == "pages":
        condition += " && !github.event.pull_request"
    assert step["if"] == f"${{{{ {condition} }}}}"


@pytest.mark.skipif(shutil.which("bash") is None, reason="the Action's step is a bash script")
@pytest.mark.parametrize(("mode", "status"), [("artifact", 0), ("pages", 0), ("everywhere", 1)])
def test_the_report_step_accepts_only_artifact_or_pages(tmp_path: Path, mode: str, status: int) -> None:
    fake = tmp_path / "bin" / "uv"
    fake.parent.mkdir()
    fake.write_text('#!/usr/bin/env bash\necho "$@" > "$RUNNER_TEMP/args"\n', encoding="utf-8", newline="\n")
    fake.chmod(0o755)
    output = tmp_path / "output"
    output.touch()
    env = {
        **os.environ,
        "PATH": f"{fake.parent}{os.pathsep}{os.environ['PATH']}",
        "RUNNER_TEMP": str(tmp_path),
        "GITHUB_OUTPUT": str(output),
        "GITHUB_ACTION_PATH": str(ROOT),
        "BYLAW_REPORT": mode,
    }
    script = tmp_path / "step.sh"
    script.write_text(str(_steps()["report"]["run"]), encoding="utf-8", newline="\n")

    done = subprocess.run(
        [str(shutil.which("bash")), "-eo", "pipefail", script.name], cwd=tmp_path, env=env, check=False
    )

    assert done.returncode == status
    if status == 0:
        assert "report --output" in (tmp_path / "args").read_text(encoding="utf-8")
        assert output.read_text(encoding="utf-8").startswith("dir=")
