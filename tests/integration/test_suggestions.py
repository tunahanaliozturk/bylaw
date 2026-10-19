"""LRN-3: once maintainers have dismissed the same rule often enough, bylaw opens a pull request that adds a
suppression to `.bylaw.toml`, and never applies it itself (ADR 0022)."""

import pytest
import respx

from bylaw.cli import main
from bylaw.config import load_config
from bylaw.learn import STORE_BRANCH, Record, StoredFinding, record_path
from tests.integration.fake_github import API, BASE_SHA, NUMBER, REPO, FakeGitHub

EDITORCONFIG = "root = true\n\n[*]\ntrim_trailing_whitespace = true\n"
TOML = '# Our settings.\nseverity_threshold = "suggestion"\n\n[learn]\nenabled = true\n'
RULE = ".editorconfig:4"


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


def _earlier(number: int, by: str = "maintainer", outcome: str = "muted", author: str = "someone") -> Record:
    finding = StoredFinding(
        fingerprint=f"{number:016x}",
        category="rule",
        rule=RULE,
        file="app.py",
        outcome=outcome,
        by=by,
    )
    return Record(
        pull_request=number, author=author, merged=True, closed_at=None, head_sha="h", findings=(finding,)
    )


def _closed_with_a_mute(*earlier: Record) -> FakeGitHub:
    """Pull request 5 reviewed, its trailing whitespace finding muted by a maintainer, then merged."""
    github = FakeGitHub(base={".editorconfig": EDITORCONFIG, ".bylaw.toml": TOML})
    github.put_branch(STORE_BRANCH, {record_path(r.pull_request): r.model_dump_json() for r in earlier})
    assert _run(github, "review", "--post") == 0
    github.reply(0, "bylaw: ignore", "lead")
    github.merged = True
    return github


def test_a_rule_muted_in_three_pull_requests_gets_a_suggestion_pull_request() -> None:
    github = _closed_with_a_mute(_earlier(1), _earlier(2, by="other"))

    assert _run(github, "learn") == 0

    (suggestion,) = github.opened
    assert suggestion["base"] == "main"
    assert suggestion["head"].startswith("bylaw/suppress-")
    toml = (github.files(suggestion["head"]) or {})[".bylaw.toml"]
    assert toml.startswith(TOML)
    (added,) = load_config(toml).suppress
    assert (added.rule, added.paths) == (RULE, ("**",))
    # The suggestion is made on top of the base branch, and the base branch itself is untouched.
    assert github.commits[github.branches[suggestion["head"]]]["parents"] == [BASE_SHA]
    assert github.branches["main"] == BASE_SHA
    body = suggestion["body"]
    assert "#1, #2 and #5" in body
    assert "`lead`" in body and "`other`" in body and "@" not in body
    assert "never suggests hiding a security finding" in body


def test_below_the_threshold_nothing_is_suggested() -> None:
    github = _closed_with_a_mute(_earlier(1))

    assert _run(github, "learn") == 0

    assert github.opened == []


def test_a_suggestion_already_made_is_not_made_again_even_after_it_was_closed() -> None:
    github = _closed_with_a_mute(_earlier(1), _earlier(2))
    assert _run(github, "learn") == 0
    github.opened[0]["state"] = "closed"

    assert _run(github, "learn") == 0

    assert len(github.opened) == 1


def test_a_rule_already_suppressed_is_not_suggested() -> None:
    suppressed = TOML + f'\n[[suppress]]\nrule = "{RULE}"\npaths = ["docs/**"]\nreason = "Docs."\n'
    github = _closed_with_a_mute(_earlier(1), _earlier(2))
    github.base[".bylaw.toml"] = suppressed

    assert _run(github, "learn") == 0

    assert github.opened == []


def test_a_token_that_may_not_open_pull_requests_fails_and_says_what_to_allow(
    capsys: pytest.CaptureFixture[str],
) -> None:
    github = _closed_with_a_mute(_earlier(1), _earlier(2))
    github.refuse_pulls = True

    assert _run(github, "learn") == 2

    error = capsys.readouterr().err
    assert "pull-requests: write" in error
    assert "allows GitHub Actions to create pull requests" in error
