import base64
from collections.abc import Sequence

import httpx
import pytest
import respx

from bylaw.config import ConfigError, load_config
from bylaw.trackers import WorkItemRef, parse_work_item_refs, read_work_items

TRACKERS = """
[jira]
url = "https://acme.atlassian.net"
projects = ["PROJ", "OPS"]

[azure_boards]
organization = "acme"
projects = ["Fabrikam"]

[linear]
teams = ["ENG"]
"""


def test_allowed_keys_in_the_title_body_and_commits_become_work_item_refs() -> None:
    config = load_config(TRACKERS)

    refs = parse_work_item_refs(
        ["PROJ-12: add login", "Implements AB#345 and ENG-7.", "fix: OPS-3 timeout\n\nAlso PROJ-12"], config
    )

    assert refs == (
        WorkItemRef("jira", "PROJ-12"),
        WorkItemRef("azure_boards", "AB#345"),
        WorkItemRef("linear", "ENG-7"),
        WorkItemRef("jira", "OPS-3"),
    )


def test_look_alikes_and_keys_outside_the_allow_list_are_not_references() -> None:
    config = load_config(TRACKERS)

    refs = parse_work_item_refs(
        ["Use UTF-8, SHA-256 and ISO-27001.", "See OTHER-5, proj-9, XPROJ-4, PROJ-0 and PROJ-12a."], config
    )

    assert refs == ()


def test_references_in_urls_and_branch_names_count() -> None:
    config = load_config(TRACKERS)

    refs = parse_work_item_refs(
        ["https://acme.atlassian.net/browse/PROJ-8", "Merge branch 'feature/ENG-2-signup'"], config
    )

    assert refs == (WorkItemRef("jira", "PROJ-8"), WorkItemRef("linear", "ENG-2"))


def test_nothing_is_a_reference_without_a_tracker_in_the_config() -> None:
    assert parse_work_item_refs(["PROJ-12 and AB#3 and ENG-7"], load_config(None)) == ()


def test_azure_boards_references_need_azure_boards_in_the_config() -> None:
    config = load_config('[linear]\nteams = ["ENG"]\n')

    assert parse_work_item_refs(["AB#3 and ENG-7"], config) == (WorkItemRef("linear", "ENG-7"),)


@pytest.mark.parametrize(
    "text",
    [
        '[jira]\nurl = "http://acme.atlassian.net"\nprojects = ["PROJ"]\n',
        '[jira]\nurl = "https://user:pw@acme.atlassian.net"\nprojects = ["PROJ"]\n',
        '[jira]\nurl = "https://acme.atlassian.net?x=1"\nprojects = ["PROJ"]\n',
        '[jira]\nurl = "https://acme.atlassian.net"\nprojects = []\n',
        '[jira]\nurl = "https://acme.atlassian.net"\nprojects = ["proj"]\n',
        '[jira]\nurl = "https://acme.atlassian.net"\nprojects = ["PROJ"]\ncriteria_field = "summary"\n',
        '[azure_boards]\norganization = "acme/other"\nprojects = ["Fabrikam"]\n',
        '[linear]\nteams = ["ENG"]\n[jira]\nurl = "https://acme.atlassian.net"\nprojects = ["ENG"]\n',
        '[jira]\nurl = "https://acme.atlassian.net"\nprojects = ["PROJ"]\napi_token = "secret"\n',
    ],
    ids=[
        "plain http",
        "credentials in the url",
        "query in the url",
        "empty allow list",
        "lower case key",
        "criteria field that is not a custom field",
        "organisation with a path",
        "key claimed by two trackers",
        "token in the config",
    ],
)
def test_a_tracker_setting_that_could_widen_the_reach_is_a_config_error(text: str) -> None:
    with pytest.raises(ConfigError):
        load_config(text)


def test_the_jira_url_loses_its_trailing_slash() -> None:
    config = load_config('[jira]\nurl = "https://acme.atlassian.net/"\nprojects = ["PROJ"]\n')

    assert config.jira is not None
    assert config.jira.url == "https://acme.atlassian.net"


JIRA = "https://acme.atlassian.net"
JIRA_ENV = {"JIRA_EMAIL": "dev@acme.test", "JIRA_API_TOKEN": "jira-secret-token"}
JIRA_CONFIG = f'[jira]\nurl = "{JIRA}"\nprojects = ["PROJ"]\ncriteria_field = "customfield_10042"\n'


def _text(text: str) -> dict[str, object]:
    return {"type": "text", "text": text}


def _paragraph(*parts: dict[str, object]) -> dict[str, object]:
    return {"type": "paragraph", "content": list(parts)}


def _list(kind: str, *items: str) -> dict[str, object]:
    return {
        "type": kind,
        "content": [{"type": "listItem", "content": [_paragraph(_text(item))]} for item in items],
    }


def _doc(*blocks: dict[str, object]) -> dict[str, object]:
    return {"type": "doc", "version": 1, "content": list(blocks)}


def _jira_issue(key: str = "PROJ-12", **fields: object) -> dict[str, object]:
    return {"key": key, "fields": {"summary": "Sign in with SSO", "description": None, **fields}}


def _notes_leak(notes: Sequence[str], env: dict[str, str]) -> bool:
    secrets = set(env.values()) | {
        base64.b64encode(f"{a}:{b}".encode()).decode() for a in env.values() for b in env.values()
    }
    return any(secret in note for note in notes for secret in secrets)


@respx.mock
def test_a_jira_issue_becomes_a_requirement_with_criteria_from_its_description() -> None:
    description = _doc(
        _paragraph(_text("Users sign in through the company identity provider.")),
        {"type": "heading", "attrs": {"level": 2}, "content": [_text("Acceptance criteria")]},
        _list("bulletList", "A user with an SSO account signs in", "A disabled account is refused"),
    )
    route = respx.get(f"{JIRA}/rest/api/3/issue/PROJ-12").mock(
        return_value=httpx.Response(200, json=_jira_issue(description=description))
    )

    requirements, notes = read_work_items(["PROJ-12: SSO"], load_config(JIRA_CONFIG), JIRA_ENV)

    assert notes == ()
    [requirement] = requirements
    assert (requirement.source, requirement.title) == ("PROJ-12", "Sign in with SSO")
    assert [c.text for c in requirement.criteria] == [
        "A user with an SSO account signs in",
        "A disabled account is refused",
    ]
    assert not requirement.inferable
    request = route.calls.last.request
    assert request.url.params["fields"] == "summary,description,customfield_10042"
    expected = base64.b64encode(b"dev@acme.test:jira-secret-token").decode()
    assert request.headers["authorization"] == f"Basic {expected}"


@respx.mock
def test_action_items_ordered_lists_and_nested_lists_in_jira_text_become_markdown() -> None:
    description = _doc(
        {
            "type": "taskList",
            "attrs": {"localId": "t"},
            "content": [
                {
                    "type": "taskItem",
                    "attrs": {"localId": "a", "state": "TODO"},
                    "content": [_text("Log the sign-in")],
                },
                {
                    "type": "taskItem",
                    "attrs": {"localId": "b", "state": "DONE"},
                    "content": [_text("Keep the session")],
                },
            ],
        },
        {
            "type": "orderedList",
            "content": [
                {
                    "type": "listItem",
                    "content": [_paragraph(_text("Step one")), _list("bulletList", "nested point")],
                }
            ],
        },
        _paragraph(_text("Line one"), {"type": "hardBreak"}, _text("line two")),
        {"type": "codeBlock", "content": [_text("- [ ] not a criterion")]},
    )
    respx.get(f"{JIRA}/rest/api/3/issue/PROJ-12").mock(
        return_value=httpx.Response(200, json=_jira_issue(description=description))
    )

    [requirement], _ = read_work_items(["PROJ-12"], load_config(JIRA_CONFIG), JIRA_ENV)

    assert requirement.text.splitlines()[:5] == [
        "- [ ] Log the sign-in",
        "- [x] Keep the session",
        "",
        "1. Step one",
        "  - nested point",
    ]
    assert [c.text for c in requirement.criteria] == ["Log the sign-in", "Keep the session"]


@pytest.mark.parametrize(
    "field",
    [
        _doc(_paragraph(_text("Refuses an expired token")), _paragraph(_text("Logs every refusal"))),
        "Refuses an expired token\nLogs every refusal",
    ],
    ids=["rich text field", "plain text field"],
)
@respx.mock
def test_each_line_of_the_jira_criteria_field_is_a_criterion(field: object) -> None:
    respx.get(f"{JIRA}/rest/api/3/issue/PROJ-12").mock(
        return_value=httpx.Response(200, json=_jira_issue(customfield_10042=field))
    )

    [requirement], _ = read_work_items(["PROJ-12"], load_config(JIRA_CONFIG), JIRA_ENV)

    assert [c.text for c in requirement.criteria] == ["Refuses an expired token", "Logs every refusal"]


@respx.mock
def test_a_jira_issue_written_as_prose_may_get_inferred_criteria() -> None:
    description = _doc(_paragraph(_text("Make sign-in faster.")))
    respx.get(f"{JIRA}/rest/api/3/issue/PROJ-12").mock(
        return_value=httpx.Response(200, json=_jira_issue(description=description))
    )

    [requirement], notes = read_work_items(["PROJ-12"], load_config(JIRA_CONFIG), JIRA_ENV)

    assert (requirement.criteria, requirement.inferable) == ((), True)
    assert notes == ("PROJ-12 has no structured acceptance criteria.",)


@respx.mock
def test_a_jira_issue_moved_to_a_project_outside_the_allow_list_is_left_out() -> None:
    # Jira answers a moved issue's old key with the issue under its new key, not with a redirect.
    respx.get(f"{JIRA}/rest/api/3/issue/PROJ-12").mock(
        return_value=httpx.Response(
            200, json=_jira_issue("SECRET-4", description=_doc(_paragraph(_text("x"))))
        )
    )

    requirements, notes = read_work_items(["PROJ-12"], load_config(JIRA_CONFIG), JIRA_ENV)

    assert requirements == ()
    assert "PROJ-12" in notes[0] and "SECRET" not in notes[0]


@respx.mock
def test_jira_is_not_called_without_its_credentials() -> None:
    route = respx.get(url__startswith=JIRA)

    requirements, notes = read_work_items(
        ["PROJ-12"], load_config(JIRA_CONFIG), {"JIRA_EMAIL": "dev@acme.test"}
    )

    assert requirements == ()
    assert not route.called
    assert notes == ("JIRA_EMAIL and JIRA_API_TOKEN are not set, so PROJ-12 was not read from Jira.",)


@pytest.mark.parametrize(
    "answer",
    [
        httpx.Response(404, json={"errorMessages": ["Issue does not exist"]}),
        httpx.Response(401, text="unauthorised"),
        httpx.Response(500),
        httpx.Response(200, text="<html>login</html>"),
        httpx.ConnectError("connection refused"),
    ],
    ids=["missing", "bad token", "server error", "not json", "network error"],
)
@respx.mock
def test_an_unreadable_jira_issue_is_a_note_and_the_review_goes_on(
    answer: httpx.Response | Exception,
) -> None:
    respx.get(f"{JIRA}/rest/api/3/issue/PROJ-12").mock(side_effect=[answer])

    requirements, notes = read_work_items(["PROJ-12"], load_config(JIRA_CONFIG), JIRA_ENV)

    assert requirements == ()
    assert len(notes) == 1 and notes[0].startswith("Could not read PROJ-12 from Jira")
    assert not _notes_leak(notes, JIRA_ENV)


@respx.mock
def test_a_redirect_is_not_followed_with_the_credentials() -> None:
    respx.get(f"{JIRA}/rest/api/3/issue/PROJ-12").mock(
        return_value=httpx.Response(302, headers={"Location": "https://evil.test/steal"})
    )
    elsewhere = respx.get(url__startswith="https://evil.test")

    requirements, notes = read_work_items(["PROJ-12"], load_config(JIRA_CONFIG), JIRA_ENV)

    assert requirements == ()
    assert not elsewhere.called
    assert "redirect" in notes[0]


@respx.mock
def test_a_pull_request_naming_many_work_items_reads_only_the_first_ten() -> None:
    route = respx.get(url__startswith=f"{JIRA}/rest/api/3/issue/").mock(
        side_effect=lambda request: httpx.Response(
            200,
            json=_jira_issue(request.url.path.rsplit("/", 1)[-1], description=_doc(_paragraph(_text("x")))),
        )
    )

    requirements, notes = read_work_items(
        [" ".join(f"PROJ-{n}" for n in range(1, 13))], load_config(JIRA_CONFIG), JIRA_ENV
    )

    assert route.call_count == 10
    assert len(requirements) == 10
    assert notes[0] == "12 work items are referenced; only the first 10 are read. Left out: PROJ-11, PROJ-12."
