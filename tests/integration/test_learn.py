"""LRN-2: a closed pull request's outcomes go to the `bylaw-outcomes` branch, read only from trusted state."""

import json
from pathlib import Path

import pytest
import respx
from ruamel.yaml import YAML

from bylaw.cli import main
from bylaw.learn import STORE_BRANCH, Record
from tests.integration.fake_github import API, NUMBER, REPO, FakeGitHub

ROOT = Path(__file__).resolve().parents[2]
EDITORCONFIG = "root = true\n\n[*]\ntrim_trailing_whitespace = true\n"
# Every finding inline, so the trailing whitespace finding gets a thread a maintainer can reply in.
LEARN = 'severity_threshold = "suggestion"\n\n[learn]\nenabled = true\n'


@pytest.fixture(autouse=True)
def no_model(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("BYLAW_API_KEY", "ANTHROPIC_API_KEY", "GITHUB_EVENT_NAME", "GITHUB_EVENT_PATH"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("GITHUB_TOKEN", "t")
    monkeypatch.setenv("GITHUB_API_URL", API)
    monkeypatch.delenv("GITHUB_GRAPHQL_URL", raising=False)


def _run(github: FakeGitHub, *args: str) -> int:
    with respx.mock(assert_all_called=False) as router:
        router.route(host="api.github.test").mock(side_effect=github)
        return main([*args, "--pr", str(NUMBER), "--repo", REPO])


def _reviewed(toml: str = LEARN) -> FakeGitHub:
    """A pull request bylaw reviewed once: one inline finding on trailing whitespace, then merged."""
    github = FakeGitHub(base={".editorconfig": EDITORCONFIG, ".bylaw.toml": toml})
    assert _run(github, "review", "--post") == 0
    github.merged, github.closed_at = True, "2027-08-14T10:00:00Z"
    return github


def _record(github: FakeGitHub, number: int = NUMBER) -> Record:
    text = (github.files(STORE_BRANCH) or {})[f"pulls/{number}.json"]
    return Record.model_validate_json(text)


def test_closing_a_pull_request_records_a_maintainer_s_mute_on_the_store_branch() -> None:
    github = _reviewed()
    github.reply(0, "bylaw: ignore, generated file", "maintainer")

    assert _run(github, "learn") == 0

    record = _record(github)
    assert (record.pull_request, record.author, record.merged) == (NUMBER, "contributor", True)
    assert record.closed_at == "2027-08-14T10:00:00Z"
    assert [(f.outcome, f.by, f.rule, f.file) for f in record.findings] == [
        ("muted", "maintainer", ".editorconfig:4", "app.py")
    ]
    # The store branch has no history in common with the code.
    first = github.commits[github.branches[STORE_BRANCH]]
    assert first["parents"] == []


def test_with_learning_off_closing_a_pull_request_writes_nothing() -> None:
    github = _reviewed(toml="")

    assert _run(github, "learn") == 0

    assert STORE_BRANCH not in github.branches
    assert github.calls_to("POST", f"/repos/{REPO}/git/") == []


def test_the_author_muting_their_own_finding_is_recorded_as_left_open() -> None:
    github = _reviewed()
    github.reply(0, "bylaw: ignore", "contributor")

    assert _run(github, "learn") == 0

    assert [(f.outcome, f.by) for f in _record(github).findings] == [("open", None)]


def test_a_summary_a_person_wrote_records_nothing() -> None:
    # A member with read access could write a summary whose state says maintainers muted everything.
    github = _reviewed()
    github.comments[0]["user"] = {"type": "User", "login": "member"}
    github.comments[0]["author_association"] = "MEMBER"

    assert _run(github, "learn") == 0

    assert STORE_BRANCH not in github.branches


def test_a_record_written_while_another_pull_request_closes_lands_on_top_of_theirs() -> None:
    github = _reviewed()
    assert _run(github, "learn") == 0
    github.races = 1
    github.merged = False

    assert _run(github, "learn") == 0

    files = github.files(STORE_BRANCH) or {}
    assert sorted(files) == ["pulls/5.json", "pulls/900.json"]
    assert _record(github).merged is False


def test_closing_again_replaces_the_record_instead_of_adding_one() -> None:
    github = _reviewed()
    assert _run(github, "learn") == 0
    github.reply(0, "bylaw: ignore", "maintainer")

    assert _run(github, "learn") == 0

    assert list(github.files(STORE_BRANCH) or {}) == ["pulls/5.json"]
    assert [f.outcome for f in _record(github).findings] == ["muted"]


def test_a_token_that_cannot_write_fails_and_names_the_permission(capsys: pytest.CaptureFixture[str]) -> None:
    github = _reviewed()
    github.read_only = True

    assert _run(github, "learn") == 2

    assert "contents: write" in capsys.readouterr().err


def test_a_record_file_is_plain_json_a_person_can_read() -> None:
    github = _reviewed()

    assert _run(github, "learn") == 0

    raw = json.loads((github.files(STORE_BRANCH) or {})["pulls/5.json"])
    assert raw["schema_version"] == 1
    assert raw["criteria"] == {"met": 0, "partial": 0, "missing": 0, "not assessed": 0}


def _action_steps() -> list[dict[str, object]]:
    action = YAML(typ="safe").load((ROOT / "action.yml").read_text(encoding="utf-8"))
    steps: list[dict[str, object]] = action["runs"]["steps"]
    return steps


def test_the_action_records_outcomes_when_the_pull_request_closes_and_reviews_otherwise() -> None:
    steps = {str(s.get("id")): s for s in _action_steps()}

    assert steps["review"]["if"] == "${{ github.event.action != 'closed' }}"
    assert steps["learn"]["if"] == "${{ github.event.action == 'closed' }}"
    assert 'bylaw learn --pr "$BYLAW_PR"' in str(steps["learn"]["run"])
