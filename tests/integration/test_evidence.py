"""The evidence file of a pull request review (ADR 0021), and the Action step that uploads it."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest
import respx
from ruamel.yaml import YAML

from bylaw.cli import main
from bylaw.evidence import (
    Evidence,
    EvidenceControl,
    EvidenceCriterion,
    EvidenceFinding,
    EvidenceProfile,
    EvidenceRequirement,
)
from tests.integration.fake_github import API, HEAD_SHA, NUMBER, REPO, FakeGitHub

ROOT = Path(__file__).resolve().parents[2]
EDITORCONFIG = "root = true\n\n[*]\ntrim_trailing_whitespace = true\n"


@pytest.fixture(autouse=True)
def no_model(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("BYLAW_API_KEY", "ANTHROPIC_API_KEY", "GITHUB_EVENT_NAME", "GITHUB_EVENT_PATH"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("GITHUB_TOKEN", "t")
    monkeypatch.setenv("GITHUB_API_URL", API)
    monkeypatch.delenv("GITHUB_GRAPHQL_URL", raising=False)


def test_a_posted_review_with_a_profile_leaves_an_evidence_file_for_the_pull_request(tmp_path: Path) -> None:
    github = FakeGitHub(base={".editorconfig": EDITORCONFIG, ".bylaw.toml": 'profiles = ["iso27001"]\n'})
    evidence = tmp_path / "evidence.json"
    with respx.mock(assert_all_called=False) as router:
        router.route(host="api.github.test").mock(side_effect=github)
        code = main(["review", "--pr", str(NUMBER), "--repo", REPO, "--post", "--evidence", str(evidence)])

    record = Evidence.model_validate_json(evidence.read_bytes())
    assert code == 0
    assert (record.repository, record.pull_request, record.head_sha) == (REPO, NUMBER, HEAD_SHA)
    assert record.model_review is False
    assert [f.file for f in record.findings] == ["app.py"]
    assert record.files_changed == ("app.py",)
    assert "### Change management evidence" in github.comments[0]["body"]


def _action_steps() -> list[dict[str, object]]:
    action = YAML(typ="safe").load((ROOT / "action.yml").read_text(encoding="utf-8"))
    steps: list[dict[str, object]] = action["runs"]["steps"]
    return steps


def test_the_action_uploads_the_evidence_with_the_official_action_pinned_by_commit() -> None:
    upload = next(s for s in _action_steps() if str(s.get("uses", "")).startswith("actions/upload-artifact@"))

    sha = str(upload["uses"]).partition("@")[2]
    assert len(sha) == 40 and all(c in "0123456789abcdef" for c in sha)
    # Uploaded even when fail-on failed the review step, and only when the review wrote a file.
    assert upload["if"] == "${{ !cancelled() && steps.review.outputs.evidence != '' }}"
    assert upload["with"]["path"] == "${{ steps.review.outputs.evidence }}"  # type: ignore[index]


@pytest.mark.skipif(shutil.which("bash") is None, reason="the Action's step is a bash script")
@pytest.mark.parametrize(("writes", "status"), [(True, 1), (False, 0)])
def test_the_review_step_names_the_evidence_file_only_when_bylaw_wrote_one(
    tmp_path: Path, writes: bool, status: int
) -> None:
    step = next(s for s in _action_steps() if s.get("id") == "review")
    # A stand-in for uv: records its arguments, writes the evidence file if asked, exits as bylaw would.
    fake = tmp_path / "bin" / "uv"
    fake.parent.mkdir()
    write = 'echo {} > "$path"' if writes else "true"
    fake.write_text(
        "#!/usr/bin/env bash\n"
        'echo "$@" > "$RUNNER_TEMP/args"\n'
        'while [ $# -gt 0 ]; do if [ "$1" = --evidence ]; then path=$2; fi; shift; done\n'
        f"{write}\nexit {status}\n",
        encoding="utf-8",
        newline="\n",
    )
    fake.chmod(0o755)
    output = tmp_path / "output"
    output.touch()
    env = {
        **os.environ,
        "PATH": f"{fake.parent}{os.pathsep}{os.environ['PATH']}",
        "RUNNER_TEMP": str(tmp_path),
        "GITHUB_OUTPUT": str(output),
        "GITHUB_ACTION_PATH": str(ROOT),
        "BYLAW_PR": "5",
        "BYLAW_PROVIDER": "anthropic",
        "BYLAW_FAIL_ON": "high",
    }
    script = tmp_path / "step.sh"
    script.write_text(str(step["run"]), encoding="utf-8", newline="\n")

    # The full path: on Windows a bare "bash" can start WSL's instead of the one on PATH.
    bash = str(shutil.which("bash"))
    done = subprocess.run([bash, "-eo", "pipefail", script.name], cwd=tmp_path, env=env, check=False)

    assert done.returncode == status
    assert "--evidence" in (tmp_path / "args").read_text(encoding="utf-8").split()
    named = [line.partition("=") for line in output.read_text(encoding="utf-8").splitlines()]
    expected = [("evidence", tmp_path / "bylaw" / "evidence-pr-5.json")] if writes else []
    assert [(key, Path(value)) for key, _, value in named] == expected


def test_the_evidence_schema_is_documented_field_by_field() -> None:
    doc = (ROOT / "docs" / "compliance.md").read_text(encoding="utf-8")
    models = (
        Evidence,
        EvidenceFinding,
        EvidenceControl,
        EvidenceRequirement,
        EvidenceCriterion,
        EvidenceProfile,
    )
    fields = {name for model in models for name in model.model_fields}

    assert sorted(f for f in fields if f"`{f}`" not in doc) == []
