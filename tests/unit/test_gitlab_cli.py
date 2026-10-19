import json
import shlex
from collections.abc import Iterator
from pathlib import Path
from string import Template

import httpx
import pytest
import respx
from ruamel.yaml import YAML

from bylaw import cli
from bylaw.render import SUMMARY_MARKER

API = "https://gitlab.example.com/api/v4"
P = f"{API}/projects/42"
RECIPE = Path(__file__).parents[2] / "docs" / "recipes" / "gitlab-ci.yml"
MR = {
    "iid": 5,
    "title": "Add login",
    "description": "",
    "author": {"id": 7},
    "references": {"full": "group/app!5"},
    "diff_refs": {"base_sha": "b1", "start_sha": "s1", "head_sha": "h1"},
}
# A trailing space on an added line: the deterministic check reports it without a model.
DIFF = {"old_path": "app.py", "new_path": "app.py", "new_file": True, "diff": "@@ -0,0 +1 @@\n+x = 1 \n"}
EDITORCONFIG = "root = true\n\n[*]\ntrim_trailing_whitespace = true\n"


@pytest.fixture(autouse=True)
def ci_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("BYLAW_API_KEY", "ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GITHUB_EVENT_NAME", "GITLAB_TOKEN"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("CI_API_V4_URL", API)
    monkeypatch.setenv("CI_MERGE_REQUEST_IID", "5")
    monkeypatch.setenv("CI_MERGE_REQUEST_PROJECT_ID", "42")
    monkeypatch.setenv("CI_MERGE_REQUEST_SOURCE_PROJECT_ID", "42")


@pytest.fixture
def server() -> Iterator[respx.MockRouter]:
    with respx.mock(assert_all_called=False) as router:
        router.get(f"{P}/merge_requests/5").mock(return_value=httpx.Response(200, json=MR))
        router.get(f"{API}/user").mock(return_value=httpx.Response(200, json={"id": 99}))
        router.get(url__regex=r"/members/all/\d+$").mock(
            return_value=httpx.Response(200, json={"access_level": 30})
        )
        for listing in ("commits", "closes_issues", "discussions", "notes"):
            router.get(url__startswith=f"{P}/merge_requests/5/{listing}").mock(
                return_value=httpx.Response(200, json=[])
            )
        router.get(url__startswith=f"{P}/merge_requests/5/diffs").mock(
            return_value=httpx.Response(200, json=[DIFF])
        )
        router.get(url__startswith=f"{P}/repository/files/.editorconfig/raw").mock(
            return_value=httpx.Response(200, text=EDITORCONFIG)
        )
        # The trailing space is a low finding; the threshold brings it inline.
        router.get(url__startswith=f"{P}/repository/files/.bylaw.toml/raw").mock(
            return_value=httpx.Response(200, text='severity_threshold = "low"\n')
        )
        router.get(url__startswith=f"{P}/repository/").mock(return_value=httpx.Response(404, json={}))
        yield router


def test_a_merge_request_review_needs_a_gitlab_token(capsys: pytest.CaptureFixture[str]) -> None:
    code = cli.main(["review", "--gitlab-mr", "5", "--project", "42"])

    assert code == 2
    assert "GITLAB_TOKEN" in capsys.readouterr().err


def test_a_fork_pipeline_without_the_token_exits_quietly(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("CI_MERGE_REQUEST_SOURCE_PROJECT_ID", "77")

    assert cli.main(["review", "--gitlab-mr", "5", "--post"]) == 0
    assert "runs in a fork" in capsys.readouterr().err


def test_a_merge_request_is_reviewed_and_published_with_the_projects_rules(
    monkeypatch: pytest.MonkeyPatch, server: respx.MockRouter
) -> None:
    monkeypatch.setenv("GITLAB_TOKEN", "glpat-fake")
    discussion = server.post(f"{P}/merge_requests/5/discussions").mock(
        return_value=httpx.Response(201, json={})
    )
    summary = server.post(f"{P}/merge_requests/5/notes").mock(return_value=httpx.Response(201, json={}))

    code = cli.main(["review", "--gitlab-mr", "5", "--post", "--fail-on", "low"])

    assert code == 1
    position = json.loads(discussion.calls.last.request.content)["position"]
    assert (position["new_path"], position["new_line"], position["head_sha"]) == ("app.py", 1, "h1")
    assert json.loads(summary.calls.last.request.content)["body"].startswith(SUMMARY_MARKER)


def test_the_gitlab_ci_recipe_runs_on_merge_request_pipelines_and_its_command_works(
    monkeypatch: pytest.MonkeyPatch, server: respx.MockRouter
) -> None:
    job = YAML(typ="safe").load(RECIPE.read_text(encoding="utf-8"))["bylaw"]
    monkeypatch.setenv("GITLAB_TOKEN", "glpat-fake")
    summary = server.post(f"{P}/merge_requests/5/notes").mock(return_value=httpx.Response(201, json={}))
    server.post(f"{P}/merge_requests/5/discussions").mock(return_value=httpx.Response(201, json={}))

    assert job["rules"] == [{"if": '$CI_PIPELINE_SOURCE == "merge_request_event"'}]
    # bylaw reads everything through the API; no checkout means uv finds no configuration from the branch.
    assert job["variables"]["GIT_STRATEGY"] == "none"
    (command,) = job["script"]
    variables = {"CI_MERGE_REQUEST_IID": "5", "CI_MERGE_REQUEST_PROJECT_ID": "42", **job["variables"]}
    argv = shlex.split(Template(command).substitute(variables))
    assert argv[:2] == ["uvx", f"bylaw@{job['variables']['BYLAW_VERSION']}"]

    assert cli.main(argv[2:]) == 0
    assert summary.called


def test_the_pull_request_flags_are_unchanged() -> None:
    with pytest.raises(SystemExit):
        cli.main(["review", "--pr", "5", "--gitlab-mr", "5"])
